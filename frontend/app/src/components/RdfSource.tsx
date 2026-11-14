import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { DescribeResponse, DescribeTriple } from '../api/client';
import { useAppStore } from '../store/appStore';
import { describeFailure, describeFailureText } from '../lib/errors';
import type { DescribeFailure } from '../lib/errors';

export function localNameOf(value: string): string {
  const tail = value.replace(/[#/]+$/, '').split(/[#/]/).pop() ?? value;
  try {
    return decodeURIComponent(tail);
  } catch {
    return tail;
  }
}

/** 结构化三元组列表（#147）：谓词 + 取值；字面量带引号 / 类型 / 语言。 */
export function SourceTriples({
  triples, onSelect,
}: {
  triples: DescribeTriple[];
  onSelect?: (id: string) => void;
}) {
  if (triples.length === 0) {
    return <div className="inspector-source-note">该元素在当前本体中无任何三元组。</div>;
  }
  return (
    <ul className="source-triples">
      {triples.map((triple, index) => {
        const resource = triple.object_kind !== 'literal';
        const suffix = [
          triple.object_language ? `@${triple.object_language}` : '',
          triple.object_datatype ? `^^${localNameOf(triple.object_datatype)}` : '',
        ].join('');
        return (
          <li key={`${triple.predicate}-${triple.object}-${index}`} className="source-triple">
            <span className="source-predicate" title={triple.predicate}>
              {localNameOf(triple.predicate)}
            </span>
            <span className="source-object">
              {resource ? (
                onSelect ? (
                  <button
                    type="button"
                    className="source-resource"
                    title={triple.object}
                    onClick={() => onSelect(localNameOf(triple.object))}
                  >
                    {localNameOf(triple.object)}
                  </button>
                ) : (
                  <code title={triple.object}>{localNameOf(triple.object)}</code>
                )
              ) : (
                <span className="source-literal">
                  “{triple.object}”<span className="source-suffix">{suffix}</span>
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function useLazyDescribe(id: string | null, eager: boolean, includeAsObject: boolean) {
  const [data, setData] = useState<DescribeResponse | null>(null);
  const [failure, setFailure] = useState<DescribeFailure | null>(null);
  const [wanted, setWanted] = useState(eager);
  const requested = useRef<string | null>(null);

  useEffect(() => {
    setData(null);
    setFailure(null);
    requested.current = null;
    setWanted(eager);
  }, [id, eager, includeAsObject]);

  useEffect(() => {
    if (!id || !wanted || requested.current === id) return;
    requested.current = id;
    let cancelled = false;
    api.describe(id, includeAsObject)
      .then((next) => { if (!cancelled) setData(next); })
      .catch((error) => { if (!cancelled) setFailure(describeFailure(error)); });
    return () => { cancelled = true; };
  }, [id, wanted, includeAsObject]);

  return { data, failure, open: () => setWanted(true) };
}

function SourceBody({
  data, failure, note, onSelect,
}: {
  data: DescribeResponse | null;
  failure: DescribeFailure | null;
  note?: string;
  onSelect?: (id: string) => void;
}) {
  if (failure) return <div className="element-readonly-note">{describeFailureText(failure)}</div>;
  if (!data) return <div className="inspector-source-note">正在读取原始三元组…</div>;
  return (
    <div className="inspector-source-body">
      {note && <div className="inspector-source-note">{note}</div>}
      <SourceTriples triples={data.triples} onSelect={onSelect} />
      <details className="source-raw">
        <summary>原始文本（N-Triples，可复制）</summary>
        <pre className="inspector-ntriples">{data.ntriples || '（没有可展示的三元组）'}</pre>
      </details>
    </div>
  );
}

/**
 * 节点原始三元组（#144 / #147）：身份区补 IRI / 局部名，展开时读取 describe。
 * 用于 ElementEditor（导入态节点实际走的是只读表单，而不是 Inspector）。
 */
export function NodeSource({ id, includeAsObject = false }: { id: string; includeAsObject?: boolean }) {
  const mode = useAppStore((state) => state.ontologyMode);
  const withIdentity = mode === 'imported' || mode === 'generic';
  const { data, failure, open } = useLazyDescribe(id, withIdentity, includeAsObject);
  return (
    <div className="rdf-source">
      {withIdentity && (
        <div className="element-identity">
          <div><b>IRI</b>：<code className="inspector-iri">{data?.iri ?? id}</code></div>
          <div><b>局部名</b>：<code>{data?.local_name ?? localNameOf(id)}</code></div>
        </div>
      )}
      <details
        className="inspector-source"
        onToggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) open(); }}
      >
        <summary>源码视角（原始三元组）</summary>
        <SourceBody
          data={data}
          failure={failure}
          note={includeAsObject
            ? '以该元素作主语或宾语的全部三元组（类能看到实例 / 子类入边）。'
            : '以该元素作主语的全部三元组（对象属性与字面量都在）。'}
        />
      </details>
    </div>
  );
}

/**
 * 关系原始三元组（#147）：结构化一行 + 原始文本兜底；读取失败按类型分流。
 */
export function EdgeSource({
  source, predicate, target,
}: {
  source: string;
  predicate: string;
  target: string;
}) {
  const { data, failure, open } = useLazyDescribe(source, false, false);
  const wanted = predicate === 'rdf:type' ? 'type' : predicate;
  const triple = data?.triples.find((item) =>
    localNameOf(item.predicate) === wanted
    && localNameOf(item.object).toLowerCase() === localNameOf(target).toLowerCase());
  const fallback: DescribeTriple = {
    subject: source,
    predicate,
    object: target,
    object_kind: 'iri',
  };
  return (
    <details
      className="inspector-source"
      onToggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) open(); }}
    >
      <summary>源码视角（原始三元组）</summary>
      <div className="inspector-source-body">
        {failure && <div className="element-readonly-note">{describeFailureText(failure)}</div>}
        {!data && !failure && <div className="inspector-source-note">正在读取原始三元组…</div>}
        {data && !triple && (
          <div className="inspector-source-note">当前图中未定位到完整 IRI，以下用短名表示。</div>
        )}
        <SourceTriples triples={triple ? [triple] : [fallback]} />
        {triple && (
          <details className="source-raw">
            <summary>原始文本（N-Triples，可复制）</summary>
            <pre className="inspector-ntriples">
              {`<${triple.subject}> <${triple.predicate}> ${triple.object_kind === 'literal' ? JSON.stringify(triple.object) : `<${triple.object}>`} .`}
            </pre>
          </details>
        )}
      </div>
    </details>
  );
}
