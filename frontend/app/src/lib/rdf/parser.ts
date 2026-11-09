import type {
  Ontology,
  EntityType,
  EntityInstance,
  InstanceAssertion,
  Property,
  Relationship,
  RelationshipAttribute,
  DataBinding,
} from '../../data/ontology';

export class RDFParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RDFParseError';
  }
}

/**
 * Get the text content of a child element by local name within a parent element.
 * Searches across common RDF/OWL namespaces.
 */
function getChildText(
  parent: Element,
  localName: string,
  namespace?: string,
): string | null {
  // Try namespace-aware lookup first
  if (namespace) {
    const els = parent.getElementsByTagNameNS(namespace, localName);
    if (els.length > 0) return els[0].textContent;
  }

  // Fallback: try all children by local name match
  for (let i = 0; i < parent.children.length; i++) {
    const child = parent.children[i];
    const childLocal = child.localName || child.tagName.split(':').pop();
    if (childLocal === localName) {
      return child.textContent;
    }
  }
  return null;
}

/**
 * Get the rdf:resource attribute from a child element.
 */
function getChildResource(
  parent: Element,
  localName: string,
): string | null {
  for (let i = 0; i < parent.children.length; i++) {
    const child = parent.children[i];
    const childLocal = child.localName || child.tagName.split(':').pop();
    if (childLocal === localName) {
      return (
        child.getAttribute('rdf:resource') ||
        child.getAttributeNS('http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'resource')
      );
    }
  }
  return null;
}

/**
 * Get all text values from children with a given local name.
 */
function getChildTexts(parent: Element, localName: string): string[] {
  const results: string[] = [];
  for (let i = 0; i < parent.children.length; i++) {
    const child = parent.children[i];
    const childLocal = child.localName || child.tagName.split(':').pop();
    if (childLocal === localName && child.textContent) {
      results.push(child.textContent);
    }
  }
  return results;
}

/**
 * Extract the local name (fragment) from a URI.
 * e.g., "http://example.org/ontology/foo/Customer" → "Customer"
 */
function localNameFromUri(uri: string): string {
  const hashIdx = uri.lastIndexOf('#');
  if (hashIdx >= 0) return uri.substring(hashIdx + 1);
  const slashIdx = uri.lastIndexOf('/');
  if (slashIdx >= 0) return uri.substring(slashIdx + 1);
  return uri;
}

/**
 * Uncapitalize the first character.
 */
function uncapitalize(str: string): string {
  return str.charAt(0).toLowerCase() + str.slice(1);
}

const VALID_PROPERTY_TYPES = ['string', 'integer', 'decimal', 'double', 'date', 'datetime', 'boolean', 'enum'] as const;
type PropertyType = (typeof VALID_PROPERTY_TYPES)[number];

function isValidPropertyType(t: string): t is PropertyType {
  return (VALID_PROPERTY_TYPES as readonly string[]).includes(t);
}

const XSD_TO_TYPE: Record<string, PropertyType> = {
  string: 'string',
  integer: 'integer',
  int: 'integer',
  long: 'integer',
  decimal: 'decimal',
  float: 'decimal',
  double: 'double',
  date: 'date',
  dateTime: 'datetime',
  boolean: 'boolean',
};

const VALID_CARDINALITIES = ['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many'] as const;
type Cardinality = (typeof VALID_CARDINALITIES)[number];

function isValidCardinality(c: string): c is Cardinality {
  return (VALID_CARDINALITIES as readonly string[]).includes(c);
}

const RDF_NS = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#';
const RDFS_NS = 'http://www.w3.org/2000/01/rdf-schema#';
const OWL_NS = 'http://www.w3.org/2002/07/owl#';

/** 解析期提示：不阻断导入，供调用方按需展示（如复合键降级）。 */
export interface RDFParseWarning {
  message: string;
  /** 可定位的目标实体 id（有则提供） */
  targetId?: string;
}

function childLocalName(el: Element): string {
  return el.localName || el.tagName.split(':').pop() || '';
}

function getChildAttr(el: Element, localName: string): string | null {
  return el.getAttribute(`rdf:${localName}`) || el.getAttributeNS(RDF_NS, localName);
}

/**
 * 读取类上的 owl:hasKey 引用的属性 IRI。
 *
 * RDF/XML 的 `rdf:parseType="Collection"` 在 DOMParser 里不会被展开成数组，
 * 子元素仍是字面写下的 `<rdf:Description rdf:about="..."/>`；因此直接取
 * 每个子元素的 rdf:about 即可。非集合写法（直接 rdf:resource）也一并兼容。
 */
function readHasKeyUris(classEl: Element): string[] {
  const uris: string[] = [];
  for (let i = 0; i < classEl.children.length; i++) {
    const child = classEl.children[i];
    if (childLocalName(child) !== 'hasKey') continue;
    const direct = getChildAttr(child, 'resource');
    if (direct) uris.push(direct);
    for (let j = 0; j < child.children.length; j++) {
      const item = child.children[j];
      const about = getChildAttr(item, 'about') || getChildAttr(item, 'resource');
      if (about) uris.push(about);
    }
  }
  return uris;
}

interface ParsedDatatypeProperty {
  about: string;
  label: string;
  domainUri: string | null;
  rangeUri: string | null;
  comment: string | null;
  isIdentifier: boolean;
  unit: string | null;
  enumValues: string | null;
  propertyType: string | null;
  relationshipAttributeOf: string | null;
  attributeType: string | null;
}

/**
 * Parse an RDF/XML (OWL) string into an Ontology and optional DataBindings.
 */
export function parseRDF(rdfXml: string): {
  ontology: Ontology;
  bindings: DataBinding[];
  warnings: RDFParseWarning[];
} {
  const parser = new DOMParser();
  const doc = parser.parseFromString(rdfXml, 'application/xml');

  // Check for XML parse errors
  const parseError = doc.querySelector('parsererror');
  if (parseError) {
    throw new RDFParseError(`Malformed XML: ${parseError.textContent?.trim() || 'parse error'}`);
  }

  const root = doc.documentElement;
  const warnings: RDFParseWarning[] = [];

  // --- Extract ontology metadata ---
  let ontologyName = '';
  let ontologyDescription = '';

  const ontologyEls = root.getElementsByTagNameNS(OWL_NS, 'Ontology');
  if (ontologyEls.length > 0) {
    const ontEl = ontologyEls[0];
    ontologyName = getChildText(ontEl, 'label', RDFS_NS) || '';
    ontologyDescription = getChildText(ontEl, 'comment', RDFS_NS) || '';
  }

  // --- Extract OWL Classes → EntityTypes ---
  const classEls = root.getElementsByTagNameNS(OWL_NS, 'Class');
  const entityMap = new Map<string, EntityType>();
  // 类 IRI → owl:hasKey 列出的属性 IRI（保持声明顺序）。
  // 只记录非空列表：空 Collection 等于没声明键，按旧行为处理。
  const keyUrisByClass = new Map<string, string[]>();
  // 类 IRI → rdfs:subClassOf 的目标 IRI（等所有类都建好后再解析成 entity id）
  const parentUriByClass = new Map<string, string>();

  for (let i = 0; i < classEls.length; i++) {
    const el = classEls[i];
    const about = el.getAttribute('rdf:about') || el.getAttributeNS(RDF_NS, 'about') || '';
    if (!about) continue;

    const className = localNameFromUri(about);
    const entityId = uncapitalize(className);
    const label = getChildText(el, 'label', RDFS_NS) || className;
    const description = getChildText(el, 'comment', RDFS_NS) || '';
    const icon = getChildText(el, 'icon') || '📦';
    const color = getChildText(el, 'color') || '#0078D4';

    entityMap.set(about, {
      id: entityId,
      name: label,
      description,
      icon,
      color,
      properties: [],
    });

    // 只认具名父类；owl:Thing 视为「无父类」，restriction 等 bnode 表达不进入草图。
    const parentUri = getChildResource(el, 'subClassOf');
    if (parentUri && parentUri !== `${OWL_NS}Thing`) parentUriByClass.set(about, parentUri);

    const keyUris = readHasKeyUris(el);
    if (keyUris.length > 0) keyUrisByClass.set(about, keyUris);
  }

  // 所有类都建好后再把父类 IRI 解析成 entity id（解析不到的父类忽略，不写悬空引用）。
  for (const [classUri, parentUri] of parentUriByClass) {
    const entity = entityMap.get(classUri);
    const parent = entityMap.get(parentUri);
    if (entity && parent && parent.id !== entity.id) entity.parent = parent.id;
  }

  // 复合键降级提示：编辑器按单布尔 isIdentifier 处理，只认第一个键。
  // 不静默丢弃——多键是合法 OWL 构造，用户有权知道这一版只读了一个。
  for (const [classUri, keyUris] of keyUrisByClass) {
    if (keyUris.length <= 1) continue;
    const entity = entityMap.get(classUri);
    warnings.push({
      message: `实体 "${entity?.name ?? localNameFromUri(classUri)}" 的 owl:hasKey 声明了 ${keyUris.length} 个属性（复合键），当前编辑器只按第一个处理`,
      targetId: entity?.id,
    });
  }

  // --- Extract DatatypeProperties → Properties + Relationship Attributes ---
  const dtPropEls = root.getElementsByTagNameNS(OWL_NS, 'DatatypeProperty');
  const parsedDtProps: ParsedDatatypeProperty[] = [];

  for (let i = 0; i < dtPropEls.length; i++) {
    const el = dtPropEls[i];
    const about = el.getAttribute('rdf:about') || el.getAttributeNS(RDF_NS, 'about') || '';
    if (!about) continue;

    const comments = getChildTexts(el, 'comment');
    const hasIdentifierComment = comments.some(c => /^identifier\s+property$/i.test(c.trim()));
    const descriptionComment = comments.find(c => !/^identifier\s+property$/i.test(c.trim())) ?? null;

    const domainUri = getChildResource(el, 'domain');
    // 双读、单写：owl:hasKey 是标准来源，<ont:isIdentifier> 与
    // "Identifier property" 注释只用于打开存量文件（2027 年后可评估移除）。
    // 同一类只要声明了 hasKey，就以 hasKey 为准——旧注解不再参与判定。
    const keyUris = domainUri ? keyUrisByClass.get(domainUri) : undefined;
    const legacyIdentifier = getChildText(el, 'isIdentifier') === 'true' || hasIdentifierComment;
    const isIdentifier = keyUris ? keyUris[0] === about : legacyIdentifier;

    parsedDtProps.push({
      about,
      label: getChildText(el, 'label', RDFS_NS) || localNameFromUri(about),
      domainUri,
      rangeUri: getChildResource(el, 'range'),
      comment: descriptionComment,
      isIdentifier,
      unit: getChildText(el, 'unit'),
      enumValues: getChildText(el, 'enumValues'),
      propertyType: getChildText(el, 'propertyType'),
      relationshipAttributeOf: getChildText(el, 'relationshipAttributeOf'),
      attributeType: getChildText(el, 'attributeType'),
    });
  }

  // Collect relationship attributes separately
  const relAttrMap = new Map<string, RelationshipAttribute[]>();
  const globalProperties: Property[] = [];

  for (const dtProp of parsedDtProps) {
    if (dtProp.relationshipAttributeOf) {
      const relId = dtProp.relationshipAttributeOf;
      if (!relAttrMap.has(relId)) {
        relAttrMap.set(relId, []);
      }
      relAttrMap.get(relId)!.push({
        name: dtProp.label,
        type: dtProp.attributeType || 'string',
      });
      continue;
    }

    // 不属于具体类的数据属性（owl:Thing / 缺省 / domain 悬空）→ 全局属性。
    // 默认本体的 has_description 就是这一类，断言里直接用 IRI 短名。
    const entity = dtProp.domainUri ? entityMap.get(dtProp.domainUri) : undefined;
    const isGlobal =
      !dtProp.domainUri ||
      dtProp.domainUri === `${OWL_NS}Thing` ||
      !entity;

    // Determine property type
    let propType: PropertyType = 'string';
    if (dtProp.propertyType && isValidPropertyType(dtProp.propertyType)) {
      propType = dtProp.propertyType;
    } else if (dtProp.rangeUri) {
      const xsdLocal = localNameFromUri(dtProp.rangeUri);
      if (XSD_TO_TYPE[xsdLocal]) {
        propType = XSD_TO_TYPE[xsdLocal];
      }
    }

    const prop: Property = {
      name: dtProp.label,
      type: propType,
      // 保留原 IRI 短名：默认本体 label 是中文（「有效期至」），不能靠 label 反推 IRI。
      iriName: localNameFromUri(dtProp.about),
    };

    if (dtProp.isIdentifier) prop.isIdentifier = true;
    if (dtProp.unit) prop.unit = dtProp.unit;
    if (dtProp.enumValues) {
      prop.values = dtProp.enumValues.split(',');
    }
    if (dtProp.comment) prop.description = dtProp.comment;

    if (isGlobal) globalProperties.push(prop);
    else entity!.properties.push(prop);
  }

  // --- Extract ObjectProperties → Relationships ---
  const objPropEls = root.getElementsByTagNameNS(OWL_NS, 'ObjectProperty');
  const relationships: Relationship[] = [];

  for (let i = 0; i < objPropEls.length; i++) {
    const el = objPropEls[i];
    const about = el.getAttribute('rdf:about') || el.getAttributeNS(RDF_NS, 'about') || '';
    if (!about) continue;

    const relId = localNameFromUri(about);
    const label = getChildText(el, 'label', RDFS_NS) || relId;
    const description = getChildText(el, 'comment', RDFS_NS) || undefined;

    // Get from/to entity IDs — prefer explicit ont:fromEntityId/toEntityId,
    // fallback to domain/range URI.  Always uncapitalize to match entity IDs.
    let fromId = uncapitalize(getChildText(el, 'fromEntityId') || '');
    let toId = uncapitalize(getChildText(el, 'toEntityId') || '');

    if (!fromId) {
      const domainUri = getChildResource(el, 'domain');
      if (domainUri) fromId = uncapitalize(localNameFromUri(domainUri));
    }
    if (!toId) {
      const rangeUri = getChildResource(el, 'range');
      if (rangeUri) toId = uncapitalize(localNameFromUri(rangeUri));
    }

    const cardinalityStr = getChildText(el, 'cardinality') || 'one-to-many';
    const cardinality: Cardinality = isValidCardinality(cardinalityStr)
      ? cardinalityStr
      : 'one-to-many';

    const rel: Relationship = {
      id: relId,
      name: label,
      from: fromId,
      to: toId,
      cardinality,
    };

    if (description) rel.description = description;

    // Attach relationship attributes
    const attrs = relAttrMap.get(relId);
    if (attrs && attrs.length > 0) {
      rel.attributes = attrs;
    }

    // Skip relationships with unresolved source or target
    if (!rel.from || !rel.to) continue;

    relationships.push(rel);
  }

  // --- Extract NamedIndividuals → EntityInstances ---
  // 只收原始断言里的类型与属性值；推理结论不在这里（§4.3）。
  const classIdByLocal = new Map<string, string>();
  for (const entity of entityMap.values()) classIdByLocal.set(entity.id.toLowerCase(), entity.id);

  const classIdOfType = (resource: string | null): string | null => {
    if (!resource) return null;
    const direct = entityMap.get(resource);
    if (direct) return direct.id;
    return classIdByLocal.get(localNameFromUri(resource).toLowerCase()) ?? null;
  };

  const instances: EntityInstance[] = [];
  const seenInstances = new Set<string>();

  /** 读取一个具名个体；返回是否真的收集到类型（供 rdf:Description 兜底判断）。 */
  const readInstance = (el: Element, requireType: boolean): boolean => {
    const about = el.getAttribute('rdf:about') || el.getAttributeNS(RDF_NS, 'about') || '';
    if (!about || entityMap.has(about)) return false;
    const id = localNameFromUri(about);
    if (!id || seenInstances.has(id)) return false;

    const types = new Set<string>();
    const assertions: InstanceAssertion[] = [];
    for (let i = 0; i < el.children.length; i++) {
      const child = el.children[i];
      const local = childLocalName(child);
      if (local === 'type') {
        const cls = classIdOfType(getChildAttr(child, 'resource'));
        if (cls) types.add(cls);
        continue;
      }
      if (local === 'label' || local === 'comment') continue;
      // 匿名嵌套（restriction 等）不是可编辑的字段值，跳过
      if (child.children.length > 0) continue;
      const resource = getChildAttr(child, 'resource');
      if (resource) {
        assertions.push({ prop: local, value: localNameFromUri(resource), isObject: true });
        continue;
      }
      const text = child.textContent ?? '';
      if (text.trim()) assertions.push({ prop: local, value: text, isObject: false });
    }

    if (requireType && types.size === 0) return false;
    seenInstances.add(id);
    instances.push({
      id,
      entityTypeId: Array.from(types)[0] ?? '',
      label: getChildText(el, 'label', RDFS_NS) || id,
      types: Array.from(types),
      assertions,
    });
    return true;
  };

  const namedIndEls = root.getElementsByTagNameNS(OWL_NS, 'NamedIndividual');
  for (let i = 0; i < namedIndEls.length; i++) {
    readInstance(namedIndEls[i], false);
  }
  // 兼容没有 owl:NamedIndividual 声明、直接用 rdf:Description + rdf:type 写个体的文件。
  const descEls = root.getElementsByTagNameNS(RDF_NS, 'Description');
  for (let i = 0; i < descEls.length; i++) {
    readInstance(descEls[i], true);
  }

  // --- Extract DataBindings ---
  const bindings: DataBinding[] = [];
  // Look for ont:DataBinding elements (they use the ontology namespace)
  const allElements = root.getElementsByTagName('*');
  for (let i = 0; i < allElements.length; i++) {
    const el = allElements[i];
    const localName = el.localName || el.tagName.split(':').pop();
    if (localName !== 'DataBinding') continue;

    const entityId = getChildText(el, 'boundEntityId') || '';
    const source = getChildText(el, 'source') || '';
    const table = getChildText(el, 'table') || '';
    const mappingTexts = getChildTexts(el, 'columnMapping');

    const columnMappings: Record<string, string> = {};
    for (const mapping of mappingTexts) {
      const eqIdx = mapping.indexOf('=');
      if (eqIdx > 0) {
        columnMappings[mapping.substring(0, eqIdx)] = mapping.substring(eqIdx + 1);
      }
    }

    if (entityId) {
      bindings.push({ entityTypeId: entityId, source, table, columnMappings });
    }
  }

  // --- Build the Ontology ---
  const entityTypes = Array.from(entityMap.values());

  if (!ontologyName && entityTypes.length === 0) {
    throw new RDFParseError('No ontology metadata or OWL classes found in the RDF document.');
  }

  const ontology: Ontology = {
    name: ontologyName || 'Imported Ontology',
    description: ontologyDescription,
    entityTypes,
    relationships,
    instances,
    globalProperties,
  };

  return { ontology, bindings, warnings };
}
