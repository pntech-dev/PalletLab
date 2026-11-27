export type ScrollbarMetrics = {
  scrollable: boolean;
  thumbSize: number;
  thumbOffset: number;
  maxScroll: number;
  maxOffset: number;
};

/** Computes custom scrollbar thumb dimensions; spans 100% of the track when content fits. */
export function computeScrollbarMetrics(
  clientSize: number,
  scrollSize: number,
  scrollPos: number,
  trackSize: number,
  minThumbSize = 32,
): ScrollbarMetrics {
  const safeTrack = Math.max(0, trackSize);
  const maxScroll = Math.max(0, scrollSize - clientSize);
  if (safeTrack === 0 || maxScroll <= 1 || clientSize <= 0) {
    return {
      scrollable: false,
      thumbSize: safeTrack,
      thumbOffset: 0,
      maxScroll: 0,
      maxOffset: 0,
    };
  }
  const ratio = clientSize / scrollSize;
  const thumbSize = Math.min(safeTrack, Math.max(Math.min(minThumbSize, safeTrack), Math.round(safeTrack * ratio)));
  const maxOffset = Math.max(0, safeTrack - thumbSize);
  const progress = Math.min(1, Math.max(0, scrollPos / maxScroll));
  return {
    scrollable: true,
    thumbSize,
    thumbOffset: maxOffset * progress,
    maxScroll,
    maxOffset,
  };
}
