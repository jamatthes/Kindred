/**
 * `web/src/charts/` — the chart widget library. Hand-written SVG, no chart dependency
 * (`CLAUDE.md`). See `types.ts` for the honesty-rule props that deliberately do not exist
 * on any widget here, and `plan/design-system.md` for the rules themselves.
 */

export { AvgBar } from './AvgBar'
export type { AvgBarItem, AvgBarProps } from './AvgBar'

export { SpreadDots } from './SpreadDots'
export type { SpreadDotsOption, SpreadDotsProps } from './SpreadDots'

export { HeatMatrix } from './HeatMatrix'
export type { HeatMatrixProps } from './HeatMatrix'

export { DistributionStrip } from './DistributionStrip'
export type { DistributionStripProps } from './DistributionStrip'

export { MiniBar, Sparkline } from './MiniBar'
export type { MiniBarProps, SparklineProps } from './MiniBar'

export { ChartEmptyState, VisuallyHidden } from './a11y'
export type { ChartBaseProps, ChartMember, ChartOption } from './types'
export { average, clamp, clampPref, jitter, layoutDots, linearScale, prefRampStep, slopeTargetWidth } from './scales'
