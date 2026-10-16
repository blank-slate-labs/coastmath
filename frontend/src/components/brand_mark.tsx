import { BRAND_MARK_COLOR, BRAND_MARK_PATH, BRAND_MARK_VIEWBOX } from "./brand_mark_path";

/** The CoastMath sailboat, so the landing page, planner and its pages read as the same product. */
export function BrandMark() {
  return (
    <svg aria-hidden="true" viewBox={BRAND_MARK_VIEWBOX}>
      <path fill={BRAND_MARK_COLOR} d={BRAND_MARK_PATH} />
    </svg>
  );
}
