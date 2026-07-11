/**
 * Sony Music Latin logotype — SVG, adapted for dark background.
 * Dot mark in Sony red, wordmark in white.
 */
export function SmlLogo({ className }: { className?: string }) {
  // Sony dots mark: 7 cols × 6 rows, some positions removed at corners
  // to match the rounded-rectangle silhouette of the official mark.
  const DOT_R   = 2.2;   // dot radius
  const SPACING = 6.2;   // center-to-center spacing
  const COLS    = 7;
  const ROWS    = 6;

  // Omit corner dots to create the rounded-rectangle silhouette
  const OMIT = new Set([
    '0,0', '6,0',          // top-left / top-right
    '0,5', '6,5',          // bottom-left / bottom-right
  ]);

  const dots: { cx: number; cy: number }[] = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      if (!OMIT.has(`${c},${r}`)) {
        dots.push({
          cx: c * SPACING + DOT_R,
          cy: r * SPACING + DOT_R,
        });
      }
    }
  }

  const markW = (COLS - 1) * SPACING + DOT_R * 2;
  const markH = (ROWS - 1) * SPACING + DOT_R * 2;

  const GAP        = 10;          // gap between mark and text
  const TEXT_Y     = markH / 2;   // vertical centre of text block
  const FONT_SIZE  = 12;
  const FONT_SMALL = 10;

  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${markW + GAP + 130} ${markH}`}
      height={markH}
      aria-label="Sony Music Latin"
      role="img"
    >
      {/* ── Dots mark ── */}
      <g>
        {dots.map(({ cx, cy }) => (
          <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={DOT_R} fill="#CC0000" />
        ))}
      </g>

      {/* ── Wordmark ── */}
      <g transform={`translate(${markW + GAP}, 0)`}>
        {/* "SONY MUSIC" */}
        <text
          x={0}
          y={TEXT_Y - 3}
          fontFamily="'DM Sans', 'Helvetica Neue', Arial, sans-serif"
          fontSize={FONT_SIZE}
          fontWeight="700"
          letterSpacing="0.08em"
          fill="#FFFFFF"
          dominantBaseline="auto"
        >
          SONY MUSIC
        </text>

        {/* Separator line */}
        <line
          x1={0}
          y1={TEXT_Y + 1}
          x2={120}
          y2={TEXT_Y + 1}
          stroke="#FFFFFF"
          strokeWidth={0.6}
          opacity={0.35}
        />

        {/* "LATIN" */}
        <text
          x={0}
          y={TEXT_Y + 5}
          fontFamily="'DM Sans', 'Helvetica Neue', Arial, sans-serif"
          fontSize={FONT_SMALL}
          fontWeight="500"
          letterSpacing="0.22em"
          fill="#999999"
          dominantBaseline="hanging"
        >
          LATIN
        </text>
      </g>
    </svg>
  );
}
