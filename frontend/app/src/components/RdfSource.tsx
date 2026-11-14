import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { DescribeResponse } from '../api/client';
import { useAppStore } from '../store/appStore';

function localNameOf(value: string): string {
  const tail = value.replace(/[#/]+$/, '').split(/[#/]/).pop() ?? value;
  return decodeURIComponent(tail);
}

function useLazyDescribe(id: string | null, eager: boolean) {
  const [data, setData] = useState<DescribeResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [wanted, setWanted] = useState(eager);
  const requested = useRef<string | null>(null);

  useEffect(() => {
    setData(null);
    setFailed(false);
    requested.current = null;
    setWanted(eager);
  }, [id, eager]);

  useEffect(() => {
    if (!id || !wanted || requested.current === id) return;
    requested.current = id;
    let cancelled = false;
    api.describe(id)
      .then((next) => { if (!cancelled) setData(next); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [id, wanted]);

  return {
    data,
    failed,
    open: () => setWanted(true),
  };
}

function SourceBody({
  data, failed, note,
}: {
  data: DescribeResponse | null;
  failed: boolean;
  note?: string;
}) {
  if (failed) return <div className="element-readonly-note">源码读取失败：该元素可能已不在当前本体中。</div>;
  if (!data) return <div className="inspector-source-note">正在读取原始三元组…</div>;
  return (
    <div className="inspector-source-body">
      {note && <div className="inspector-source-note">{note}</div>}
      <pre className="inspector-ntriples">{data.ntriples || '（没有可展示的三元组）'}</pre>
    </div>
  );
}

/**
 * 节点原始三元组（#144）：身份区补 IRI / 局部名，展开时读取 describe。
 * 用于 ElementEditor（导入态节点实际走的是只读表单，而不是 Inspector）。
 */
export function NodeSource({ id }: { id: string }) {
  const mode = useAppStore((state) => state.ontologyMode);
  const withIdentity = mode === 'imported' || mode === 'generic';
  const { data, failed, open } = useLazyDescribe(id, withIdentity);
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
        <SourceBody data={data} failed={failed} note="以该元素作主语的全部三元组（对象属性与字面量都在）。" />
      </details>
    </div>
  );
}

/**
 * 关系原始三元组（#144）：按「主语 + 谓词 + 宾语」定位当前图上的那一条。
 * 短名由后端展开成 IRI；找不到时退回短名并明确标注。
 */
export function EdgeSource({
  source, predicate, target,
}: {
  source: string;
  predicate: string;
  target: string;
}) {
  const { data, failed, open } = useLazyDescribe(source, false);
  const wanted = predicate === 'rdf:type' ? 'type' : predicate;
  const triple = data?.triples.find((item) =>
    localNameOf(item.predicate) === wanted
    && localNameOf(item.object).toLowerCase() === localNameOf(target).toLowerCase());
  const text = triple
    ? `<${triple.subject}> <${triple.predicate}> ${triple.object_kind === 'literal' ? JSON.stringify(triple.object) : `<${triple.object}>`} .`
    : `<${source}> <${predicate}> <${target}> .`;
  return (
    <details
      className="inspector-source"
      onToggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) open(); }}
    >
      <summary>源码视角（原始三元组）</summary>
      <div className="inspector-source-body">
        {failed && <div className="element-readonly-note">源码读取失败：该元素可能已不在当前本体中。</div>}
        {!data && !failed && <div className="inspector-source-note">正在读取原始三元组…</div>}
        {data && !triple && (
          <div className="inspector-source-note">当前图中未定位到完整 IRI，以下用短名表示。</div>
        )}
        <pre className="inspector-ntriples">{text}</pre>
      </div>
    </details>
  );
}
