import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * 图谱渲染错误边界：cytoscape 建元素 / 布局异常时只降级图谱面板，
 * 不再让整个应用白屏（页面其它能力——源码、右侧编辑框、物化视图——保持可用）。
 */
export default class GraphErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[GraphView] 渲染失败：', error, info);
  }

  render() {
    const { error } = this.state;
    if (error) {
      return (
        <div className="graph-shell">
          <div className="graph-fallback">
            <div className="graph-fallback-icon">⚠️</div>
            <h3>图谱渲染失败</h3>
            <p className="graph-fallback-msg">{error.message}</p>
            <p className="graph-fallback-hint">
              其它功能（OWL 源码、右侧编辑框、物化视图）不受影响。若刚在编辑器里改动过实体，可先修复对应字段再重试。
            </p>
            <button type="button" className="btn" onClick={() => this.setState({ error: null })}>
              重试渲染
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
