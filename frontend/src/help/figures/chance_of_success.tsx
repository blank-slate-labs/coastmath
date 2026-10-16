/* Engine output for the help center's example plan: single, born 1966, plan starting January 1, 2026,
   life expectancy 95, $1,000,000 in a taxable brokerage account (basis $1,000,000), $40,000 of spending that
   rises with inflation, plan defaults except a 40% bond allocation. Monte Carlo: 1,000 trials, seed 42,
   3–7 year blocks, calibrated. Reproduced from the engine with these fixed inputs. */
import { Figure } from "../help_kit";
import { LineChart } from "../help_charts";

/** [year, 10th, 25th, 50th, 75th, 90th percentile net worth, steady-return projection], nominal dollars. */
export const exampleRows: [number, number, number, number, number, number, number][] = [
  [2026, 903695, 956072, 1050855, 1118679, 1191426, 1016947],
  [2027, 844993, 967388, 1076355, 1184940, 1279472, 1033646],
  [2028, 849125, 966845, 1112791, 1216280, 1382473, 1050045],
  [2029, 826110, 954842, 1108057, 1280449, 1418480, 1066089],
  [2030, 815884, 940042, 1159919, 1338228, 1533379, 1081717],
  [2031, 765045, 943811, 1154955, 1393077, 1650942, 1096865],
  [2032, 755285, 942402, 1176233, 1475829, 1744086, 1111465],
  [2033, 736868, 938922, 1209473, 1522714, 1861436, 1125440],
  [2034, 726794, 936289, 1262392, 1595547, 1960457, 1138712],
  [2035, 700499, 917567, 1236553, 1649030, 2052218, 1151193],
  [2036, 665616, 907960, 1253231, 1712035, 2177830, 1162791],
  [2037, 649097, 905798, 1287465, 1773298, 2339571, 1173406],
  [2038, 608497, 891387, 1305235, 1820628, 2500296, 1182933],
  [2039, 582184, 864292, 1337811, 1887914, 2608519, 1191256],
  [2040, 546603, 869177, 1356916, 1954260, 2718399, 1198253],
  [2041, 509830, 849408, 1368980, 2015546, 2827490, 1203793],
  [2042, 470624, 833541, 1412642, 2098248, 2927024, 1207736],
  [2043, 421581, 806912, 1421444, 2198641, 3097985, 1209931],
  [2044, 372605, 792028, 1435419, 2276327, 3245577, 1210218],
  [2045, 324680, 762790, 1427118, 2320856, 3385770, 1208425],
  [2046, 264203, 722920, 1462917, 2446209, 3572345, 1204368],
  [2047, 207954, 675611, 1462463, 2506513, 3698620, 1197852],
  [2048, 146521, 648554, 1465654, 2569463, 3963867, 1188667],
  [2049, 53558, 590894, 1464605, 2680611, 4109049, 1176588],
  [2050, -56554, 545909, 1496442, 2789256, 4384975, 1161379],
  [2051, -131409, 490954, 1444973, 2794446, 4627238, 1142784],
  [2052, -215355, 410632, 1452018, 2930090, 4801611, 1120532],
  [2053, -314718, 331933, 1472230, 3069464, 5053376, 1094334],
  [2054, -419476, 235657, 1469517, 3085855, 5246729, 1063880],
  [2055, -507483, 151119, 1464069, 3278797, 5670521, 1028842],
  [2056, -618184, 51059, 1404668, 3290173, 5733979, 988870],
  [2057, -747828, -54139, 1417931, 3428104, 6136271, 943590],
  [2058, -884473, -148552, 1403716, 3585274, 6435965, 892604],
  [2059, -1032042, -221130, 1438848, 3756886, 6915241, 835490],
  [2060, -1169270, -319881, 1384414, 3921615, 7286081, 771797],
];

const pick = (index: number) => exampleRows.map((row) => [row[0], row[index]] as [number, number]);

const table = {
  columns: [
    { key: "year", label: "Year" },
    { key: "p10", label: "10th percentile", format: "usd" as const },
    { key: "p50", label: "Median", format: "usd" as const },
    { key: "p90", label: "90th percentile", format: "usd" as const },
    { key: "steady", label: "Steady-return projection", format: "usd" as const },
  ],
  rows: exampleRows.map(([year, p10, , p50, , p90, steady]) => ({ year, p10, p50, p90, steady })),
};

/** Percentile net worth across 1,000 trials with the steady-return projection for reference. */
export function ExampleFan({ title, caption }: { title: string; caption?: string }) {
  return (
    <Figure title={title} caption={caption} table={table}>
      <LineChart
        label="Net worth by year: 90th percentile, median and 10th percentile of 1,000 trials, and the steady-return projection"
        series={[
          { id: "p90", label: "90th percentile", color: "blue", points: pick(5) },
          { id: "p50", label: "Median", color: "orange", points: pick(3) },
          { id: "p10", label: "10th percentile", color: "cyan", points: pick(1) },
          { id: "steady", label: "Steady-return projection", color: "gray", points: pick(6) },
        ]}
      />
    </Figure>
  );
}
