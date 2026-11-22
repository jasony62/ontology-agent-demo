import { useCallback, useEffect, useRef } from 'react';

/**
 * 内容探测（#395）：定时比对「轻量指纹」，有变化只回调、不自动刷新。
 *
 * 边界（按 issue 拍板）：
 *  - 只提示不自动更新：探测函数只读，回调交给页面挂提示条；
 *  - 12 秒一次，且只在页面可见时探：隐藏页不计时、不发请求；
 *  - 在途去重：上一轮没回来不叠加请求；
 *  - 失败静默：后端短暂不可用不影响现有内容，下一轮继续；
 *  - 卸载清理：定时器、可见性监听与在途请求一并收掉。
 *
 * 基线在首次成功探测时建立；检测到变化后立即把基线推进到当前值，
 * 避免同一变化每 12 秒重复提示。`reset()` 清空基线，下一轮静默重建——
 * 切领域、手动刷新后用。
 */
export interface UseContentProbeOptions {
  /** 返回指纹字符串；返回 null 表示本轮跳过（如响应不完整）。 */
  probe: (signal: AbortSignal) => Promise<string | null>;
  /** 指纹变化时调用；只负责提示，不负责刷新。 */
  onChanged: () => void;
  /** 轮询间隔，默认 12 秒。 */
  intervalMs?: number;
  /** 是否启用（如只在图谱页探测）。 */
  enabled?: boolean;
  /** 变化即重置基线（切领域 / 换本体）。 */
  resetKey?: string;
}

export interface ContentProbe {
  /** 清空基线：调用方完成一次「人确认的刷新」后使用。 */
  reset: () => void;
  /** 立即探一次（可见性允许时）。 */
  checkNow: () => Promise<void>;
}

export function useContentProbe({
  probe,
  onChanged,
  intervalMs = 12000,
  enabled = true,
  resetKey = '',
}: UseContentProbeOptions): ContentProbe {
  const probeRef = useRef(probe);
  const changedRef = useRef(onChanged);
  const enabledRef = useRef(enabled);
  probeRef.current = probe;
  changedRef.current = onChanged;
  enabledRef.current = enabled;

  const baseline = useRef<string | null>(null);
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);

  const check = useCallback(async () => {
    if (!enabledRef.current) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    if (inFlight.current) return;
    inFlight.current = true;
    const ac = new AbortController();
    controller.current = ac;
    try {
      const fingerprint = await probeRef.current(ac.signal);
      if (ac.signal.aborted || fingerprint === null) return;
      if (baseline.current === null) {
        baseline.current = fingerprint;
        return;
      }
      if (fingerprint !== baseline.current) {
        baseline.current = fingerprint;
        changedRef.current();
      }
    } catch {
      /* 失败静默：下一轮继续，不清基线（后端恢复后仍能发现期间的变化） */
    } finally {
      if (controller.current === ac) controller.current = null;
      inFlight.current = false;
    }
  }, []);

  /** 清空基线并立即补探一次：刷新 / 切领域后，用当前内容重建基线 */
  const reset = useCallback(() => {
    baseline.current = null;
    void check();
  }, [check]);

  // 切领域 / 换本体：旧基线没有意义；立即补探一次，尽快建立新基线
  useEffect(() => {
    baseline.current = null;
    void check();
  }, [resetKey, check]);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      void check();
    }, intervalMs);
    const onVisibility = () => {
      // 从后台切回立即补探一次；不重置基线，隐藏期间的变化照样能发现
      if (!document.hidden) void check();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      controller.current?.abort();
      controller.current = null;
      inFlight.current = false;
    };
  }, [check, enabled, intervalMs]);

  return { reset, checkNow: check };
}

export default useContentProbe;
