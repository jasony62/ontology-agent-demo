/** 行内术语帮助：hover / 读屏可读，只放业务解释。 */
export default function HelpTip({ text }: { text: string }) {
  return (
    <span className="cq-help" title={text} aria-label={text}>
      ?
    </span>
  );
}
