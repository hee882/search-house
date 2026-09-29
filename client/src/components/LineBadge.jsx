import { getLineColor, getShortLineName } from '../lib/stations';
import { buildUniqueKeys } from '../lib/keys';

function LineBadge({ line }) {
  if (!line) return null;
  const lines = line.split(/[,,/]/);
  const lineKeys = buildUniqueKeys(lines, getShortLineName);
  return (
    <div className="flex gap-1 items-center flex-nowrap">
      {lines.map((l, i) => (
        <div key={lineKeys[i]} className="px-1.5 py-0.5 rounded-md text-[8px] font-black text-white shadow-sm flex items-center justify-center whitespace-nowrap leading-tight" style={{ backgroundColor: getLineColor(l) }}>
          {getShortLineName(l)}
        </div>
      ))}
    </div>
  );
}

export default LineBadge;
