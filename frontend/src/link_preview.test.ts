import { readFileSync } from "node:fs";
import { join } from "node:path";

// Link-preview crawlers (iMessage, Slack, X, WhatsApp) read only the static HTML head, need an
// absolute image URL, and lay the card out from the declared size before the image arrives.
// The images are committed under public/.
const read = (file: string) => readFileSync(join(__dirname, "..", file));

const meta = (html: string, key: string) =>
  new RegExp(`<meta (?:property|name)="${key}" content="([^"]*)"`).exec(html)?.[1];

/** Width and height from a PNG's IHDR chunk. */
function pngSize(file: string) {
  const png = read(file);
  expect(png.subarray(1, 4).toString("latin1")).toBe("PNG");
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

describe("link previews", () => {
  it("points crawlers at the rendered card and a PNG touch icon", () => {
    const html = read("index.html").toString("utf8");
    // The self-hosted build doesn't know its host, so its builder makes the image root-relative.
    const raw = meta(html, "og:image") ?? "";
    expect(raw).toMatch(/^(https:\/\/|\/)/);
    const image = new URL(raw, "https://self-hosted.invalid");
    expect(pngSize(`public${image.pathname}`)).toEqual({
      width: Number(meta(html, "og:image:width")),
      height: Number(meta(html, "og:image:height")),
    });
    expect(meta(html, "og:image:alt")).toBeTruthy();
    expect(meta(html, "og:site_name")).toBe("CoastMath");
    expect(meta(html, "twitter:card")).toBe("summary_large_image");
    // iOS ignores SVG touch icons.
    const icon = /<link rel="apple-touch-icon" href="([^"]+)"/.exec(html)?.[1];
    expect(pngSize(`public${icon}`)).toEqual({ width: 180, height: 180 });
  });

  it("names the app under the image", () => {
    const html = read("index.html").toString("utf8");
    expect(meta(html, "og:title")).toMatch(/^CoastMath — /);
    expect(meta(html, "og:description")).toBeTruthy();
  });
});
