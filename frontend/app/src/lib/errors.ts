/** describe 失败的两类语义：#147 —— 端点不可用 vs 本体里真无。 */
export type DescribeFailure = 'unavailable' | 'missing';

export function describeFailure(error: unknown): DescribeFailure {
  const status = (error as { status?: number } | null)?.status;
  const message = error instanceof Error ? error.message : String(error);
  if (status === 404 || status === 405 || status === 501 || status === undefined) {
    return 'unavailable';
  }
  if (status >= 500) return 'unavailable';
  // 400 通常是短名解析不到 / 歧义：元素不在当前本体里。
  if (/Failed to fetch|NetworkError|Load failed|timeout|超时/i.test(message)) {
    return 'unavailable';
  }
  return 'missing';
}

export function describeFailureText(kind: DescribeFailure): string {
  return kind === 'unavailable'
    ? '源码接口暂不可用，请确认后端已更新到含 /api/ontology/describe 的版本。'
    : '该元素在当前本体中无任何三元组。';
}
