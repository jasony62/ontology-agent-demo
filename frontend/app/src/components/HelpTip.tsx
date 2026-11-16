/** 行内术语帮助：hover 与键盘 focus 都显示自带浮层，只放业务解释。 */
export default function HelpTip({ text }: { text: string }) {
  return (
    <button type="button" className="cq-help" aria-label={text}>
      ?
      <span className="cq-help-pop" role="tooltip">{text}</span>
    </button>
  );
}
