import { useState } from 'react';

/**
 * 专家核对入口（#208 / #210）：默认收起，展开前不把实现标识放进 DOM。
 * leader 只看业务文案；需要核对断言 / 编号时点开才显示。
 */
export default function TechDetails({
  items,
  label = '展开看技术细节',
}: {
  items: Array<{ label: string; lines: string[] }>;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="cq-tech-entry">
      <button
        type="button"
        className="btn link cq-tech-toggle"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? '收起技术细节' : label}
      </button>
      {open && (
        <div className="cq-tech-body">
          {items.map((item, index) => (
            <div key={`${item.label}-${index}`}>
              {item.lines.filter(Boolean).map((line, lineIndex) => (
                <div key={`${lineIndex}-${line}`}>{line}</div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
