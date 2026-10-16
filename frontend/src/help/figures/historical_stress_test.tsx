/* Engine output for the help center's example plan (see chance_of_success figure): single, born 1966, plan
   starting January 1, 2026, life expectancy 95, $1,000,000 brokerage, $40,000 spending rising with
   inflation, 40% bonds. Reproduced from the engine with these fixed inputs. */
import { Figure } from "../help_kit";
import { LineChart } from "../help_charts";

/** [year, net worth replaying from 1966, net worth replaying from 2000, steady-return projection], nominal dollars. */
const rows: [number, number, number, number][] = [
  [2026, 921021, 974364, 1016947],
  [2027, 997312, 885730, 1033646],
  [2028, 1026714, 782843, 1050045],
  [2029, 910436, 870331, 1066089],
  [2030, 947119, 896648, 1081717],
  [2031, 1016772, 887428, 1096865],
  [2032, 1086348, 929466, 1111465],
  [2033, 955810, 949088, 1125440],
  [2034, 768495, 771731, 1138712],
  [2035, 883780, 808146, 1151193],
  [2036, 987925, 851412, 1162791],
  [2037, 876939, 863196, 1173406],
  [2038, 829350, 898706, 1182933],
  [2039, 838013, 983074, 1191256],
  [2040, 889037, 1045971, 1198253],
  [2041, 774671, 1003221, 1203793],
  [2042, 859055, 1016522, 1207736],
  [2043, 851565, 1098635, 1209931],
  [2044, 800662, 1014054, 1210218],
  [2045, 895849, 1175722, 1208425],
  [2046, 922061, 1286672, 1204368],
  [2047, 804143, 1419341, 1197852],
  [2048, 752753, 1112050, 1188667],
  [2049, 779597, 1227077, 1176588],
  [2050, 629775, 1325131, 1161379],
  [2051, 604198, 1594863, 1142784],
  [2052, 469586, 1470700, 1120532],
  [2053, 334520, 1205869, 1094334],
  [2054, 145994, 815838, 1063880],
  [2055, -18832, 739625, 1028842],
  [2056, -211914, 902392, 988870],
  [2057, -411411, 866145, 943590],
  [2058, -614304, 1058687, 892604],
  [2059, -820468, 1219757, 835490],
  [2060, -1032167, 912695, 771797],
];

const pick = (index: number) => rows.map((row) => [row[0], row[index]] as [number, number]);

export function ExampleReplays() {
  return (
    <Figure
      title="Example plan: net worth replaying 1966 and 2000"
      caption="Plan years 2026–2060 map to 1966–2000 and to 2000–2024 followed by 1928–1937. Negative values are unpaid spending after money runs out."
      table={{
        columns: [
          { key: "year", label: "Plan year" },
          { key: "r1966", label: "From 1966", format: "usd" },
          { key: "r2000", label: "From 2000", format: "usd" },
          { key: "steady", label: "Steady-return projection", format: "usd" },
        ],
        rows: rows.map(([year, r1966, r2000, steady]) => ({ year, r1966, r2000, steady })),
      }}
    >
      <LineChart
        label="Net worth by plan year replaying history from 1966 and from 2000, with the steady-return projection"
        markers={[{ x: 2051, label: "2000 replay reaches 1928" }]}
        series={[
          { id: "r1966", label: "Replay from 1966", color: "blue", points: pick(1) },
          { id: "r2000", label: "Replay from 2000", color: "orange", points: pick(2) },
          { id: "steady", label: "Steady-return projection", color: "gray", points: pick(3) },
        ]}
      />
    </Figure>
  );
}
