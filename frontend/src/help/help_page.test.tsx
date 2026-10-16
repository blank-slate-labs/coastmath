import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import HelpPage from "./help_page";
import { FEATURED_COUNT, POPULAR, TOPIC_GUIDE, orderedArticles } from "./help_hub";
import { articles, articlesIn, getArticleMeta, sections, stages } from "./help_catalog";
import { Callout, Formula, Ledger, Op, UIPath, V } from "./help_kit";
import type { Article } from "./help_types";

const fixture: Article = {
  intro: <p>Required distributions are taken before the year’s spending is funded.</p>,
  sections: [
    {
      id: "how-it-works",
      title: "How it works",
      body: (
        <>
          <Formula result="Distribution">
            <V>Balance</V>
            <Op>÷</Op>
            <V>Period</V>
          </Formula>
          <Callout kind="where">
            <UIPath steps={["Plan", "Accounts"]} />
          </Callout>
        </>
      ),
    },
    {
      id: "example",
      title: "Example",
      body: (
        <Ledger
          title="An example"
          rows={[
            { label: "Balance", value: 500000 },
            { op: "÷", label: "Period", value: 24.6, format: "num", digits: 1 },
            { op: "=", label: "Distribution", value: 20325 },
          ]}
        />
      ),
    },
  ],
};

const RMD = "required-minimum-distributions";
const hrefs = (root: ParentNode, selector = "a") =>
  [...root.querySelectorAll(selector)].map((a) => a.getAttribute("href"));

describe("help hub", () => {
  it("opens on the hero heading and links every article from the server-rendered hub", () => {
    const html = renderToString(<HelpPage />);
    for (const article of articles) expect(html).toContain(`href="/help/${article.slug}"`);
    render(<HelpPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: "How CoastMath works" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("opens the planner in the same tab, without a new-tab arrow", () => {
    render(<HelpPage />);
    const link = screen.getByRole("link", { name: "Open planner" });
    expect(link).toHaveAttribute("href");
    expect(link).not.toHaveAttribute("target");
    expect(link).toHaveTextContent(/^Open planner$/);
  });

  it("names only real articles by hand, and features each card’s picks from its own section", () => {
    render(<HelpPage />);
    const nav = screen.getByRole("navigation", { name: "Popular" });
    expect(hrefs(nav)).toEqual(POPULAR.map((item) => `/help/${item.slug}`));
    for (const item of POPULAR) expect(getArticleMeta(item.slug), item.slug).toBeDefined();
    for (const section of sections) {
      const { featured } = TOPIC_GUIDE[section.id];
      expect(featured).toHaveLength(Math.min(FEATURED_COUNT, articlesIn(section.id).length));
      for (const slug of featured) expect(getArticleMeta(slug)?.section, slug).toBe(section.id);
      expect(TOPIC_GUIDE[section.id].blurb).toMatch(/^[A-Z].*\.$/);
    }
  });

  it("gives every section one card with its count, three featured links and the rest collapsed", () => {
    const { container } = render(<HelpPage />);
    expect(container.querySelectorAll(".help-card")).toHaveLength(sections.length);
    for (const section of sections) {
      const card = container.querySelector<HTMLElement>(`#section-${section.id}`)!;
      const list = articlesIn(section.id);
      const ordered = orderedArticles(section.id);
      expect(
        within(card).getByRole("heading", { level: 3, name: section.title }),
      ).toBeInTheDocument();
      // The See all toggle carries the count; the card has no separate badge.
      expect(card.querySelector(".help-card-count")).toBeNull();
      expect(new Set(hrefs(card))).toEqual(new Set(list.map((meta) => `/help/${meta.slug}`)));
      expect(hrefs(card)).toHaveLength(list.length);
      expect(
        within(card)
          .getAllByRole("link")
          .map((link) => link.textContent),
      ).toEqual(ordered.slice(0, FEATURED_COUNT).map((meta) => meta.title));
    }
  });

  it("expands a card in place with its See all toggle", () => {
    const { container } = render(<HelpPage />);
    const card = container.querySelector<HTMLElement>("#section-taxes")!;
    const list = articlesIn("taxes");
    const toggle = within(card).getByRole("button", {
      name: `See all ${list.length} Taxes articles`,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toBe(
      card.querySelector(".help-card-list"),
    );
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getAllByRole("link")).toHaveLength(list.length);
    fireEvent.click(within(card).getByRole("button", { name: "Show fewer Taxes articles" }));
    expect(within(card).getAllByRole("link")).toHaveLength(FEATURED_COUNT);
  });

  it("filters to one plan-year step under the timeline and resets", () => {
    const { container } = render(<HelpPage />);
    const steps = screen.getByRole("list", { name: "How CoastMath calculates a year" });
    expect(within(steps).getAllByRole("button")).toHaveLength(stages.length);
    const taxes = within(steps).getByRole("button", { name: /^Taxes:/ });
    fireEvent.click(taxes);
    expect(taxes).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("heading", { level: 2, name: "Articles about taxes" }),
    ).toBeInTheDocument();
    const expected = articles.filter((meta) => meta.stages.includes("taxes"));
    expect(hrefs(container, ".help-year .help-results-list a")).toEqual(
      expected.map((meta) => `/help/${meta.slug}`),
    );
    expect(container.querySelectorAll(".help-card")).toHaveLength(sections.length);
    expect(screen.getByRole("status")).toHaveTextContent(`${expected.length} articles about taxes`);

    fireEvent.click(taxes);
    expect(taxes).toHaveAttribute("aria-pressed", "false");
    expect(container.querySelector(".help-results")).toBeNull();

    fireEvent.click(within(steps).getByRole("button", { name: /^Growth:/ }));
    expect(
      screen.getByRole("heading", { level: 2, name: "Articles about growth" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear step" }));
    expect(screen.queryByRole("button", { pressed: true })).toBeNull();
    expect(container.querySelector(".help-results")).toBeNull();
  });

  it("searches from the hero field, shows an empty state and resets", () => {
    const { container } = render(<HelpPage />);
    const field = screen.getByLabelText("Search help");
    fireEvent.change(field, { target: { value: "IRMAA" } });
    expect(screen.getByRole("heading", { name: "Results for “IRMAA”" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Medicare premiums and IRMAA/ })).toBeInTheDocument();
    expect(container.querySelector(".help-card")).toBeNull();
    fireEvent.change(field, { target: { value: "qqqzzz" } });
    expect(screen.getByText(/No articles match “qqqzzz”/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(screen.queryByRole("heading", { name: /Results for/ })).toBeNull();
    expect(container.querySelectorAll(".help-card")).toHaveLength(sections.length);
  });

  it("narrows search results to the selected step", () => {
    const { container } = render(<HelpPage />);
    fireEvent.click(screen.getByRole("button", { name: /^Required:/ }));
    fireEvent.change(screen.getByLabelText("Search help"), { target: { value: "distribution" } });
    expect(screen.getByRole("heading", { name: "Results for “distribution”" })).toBeInTheDocument();
    expect(screen.getByText(/^Only articles about required/)).toBeInTheDocument();
    const shown = hrefs(container, ".help-results-list a");
    expect(shown.length).toBeGreaterThan(0);
    for (const href of shown)
      expect(getArticleMeta(href!.replace("/help/", ""))!.stages).toContain("required");
  });
});

describe("help article", () => {
  const meta = getArticleMeta(RMD)!;

  it("renders the bento header, contents, body and plan-year location", () => {
    const html = renderToString(<HelpPage slug={RMD} article={fixture} />);
    expect(html).toContain("Where this happens in a plan year");
    render(<HelpPage slug={RMD} article={fixture} />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(
      screen.getByRole("heading", { level: 1, name: "Required minimum distributions" }),
    ).toBeInTheDocument();
    const toc = screen.getByRole("navigation", { name: "On this page" });
    expect(
      within(toc)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["How it works", "Example"]);
    expect(within(toc).getByRole("link", { name: "How it works" })).toHaveAttribute(
      "href",
      "#how-it-works",
    );
    expect(screen.getByText("$20,325")).toBeInTheDocument();
    expect(screen.getByText("Where to find it")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent(
      "Withdrawals and distributions",
    );
    const locator = screen.getByText("Where this happens in a plan year").parentElement!;
    expect(locator.querySelectorAll("li")).toHaveLength(stages.length);
    expect(within(locator).getAllByText("(covered)")).toHaveLength(meta.stages.length);
  });

  it("links related articles and the next article in the section", () => {
    render(<HelpPage slug={RMD} article={fixture} />);
    const related = screen.getByRole("navigation", { name: "Related" });
    expect(hrefs(related)).toEqual(meta.related.map((slug) => `/help/${slug}`));
    const siblings = articlesIn(meta.section);
    const next = siblings[siblings.findIndex((item) => item.slug === RMD) + 1];
    const link = screen.queryByRole("link", { name: /^Next in Withdrawals and distributions/ });
    if (next) expect(link).toHaveAttribute("href", `/help/${next.slug}`);
    else expect(link).toBeNull();
  });

  it("places a stage-less article in its section instead of the plan year", () => {
    const guide = articles.find((item) => !item.stages.length)!;
    render(<HelpPage slug={guide.slug} article={fixture} />);
    expect(screen.queryByText("Where this happens in a plan year")).toBeNull();
    const place = screen.getByText("In this section").parentElement!;
    const siblings = articlesIn(guide.section);
    expect(place.querySelector(".help-locator-num")).toHaveTextContent(
      String(siblings.findIndex((item) => item.slug === guide.slug) + 1),
    );
  });

  it("keeps the callout kind label beside a custom title", () => {
    render(
      <Callout kind="boundary" title="Not supported: an inherited account">
        <p>Body</p>
      </Callout>,
    );
    expect(screen.getByText("Not modeled")).toBeInTheDocument();
    expect(screen.getByText("Not supported: an inherited account")).toBeInTheDocument();
  });

  it("shows a not-found page for an unknown slug", () => {
    render(<HelpPage slug="nope" />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Article not found" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse all articles" })).toHaveAttribute(
      "href",
      "/help",
    );
  });

  it("hydrates the prerendered hub and article without mismatches", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const pages: ReactElement[] = [
      <HelpPage key="hub" />,
      <HelpPage key="article" slug={RMD} article={fixture} />,
    ];
    for (const page of pages) {
      const container = document.createElement("div");
      container.innerHTML = renderToString(page);
      document.body.appendChild(container);
      const recoverable: unknown[] = [];
      let root: ReturnType<typeof hydrateRoot> | undefined;
      await act(async () => {
        root = hydrateRoot(container, page, {
          onRecoverableError: (error) => recoverable.push(error),
        });
      });
      expect(recoverable).toEqual([]);
      act(() => root!.unmount());
      container.remove();
    }
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});

describe("search palette", () => {
  it("opens with the slash key, moves the active option with the arrows and closes with Escape", () => {
    render(<HelpPage slug={RMD} article={fixture} />);
    const opener = screen.getByRole("button", { name: "Search" });
    opener.focus();
    fireEvent.keyDown(document, { key: "/" });
    const dialog = screen.getByRole("dialog", { name: "Help search" });
    const input = within(dialog).getByRole("combobox");
    expect(input).toHaveFocus();
    expect(document.body).toHaveClass("help-scroll-lock");
    fireEvent.change(input, { target: { value: "roth conversion" } });
    expect(within(dialog).getAllByRole("option")[0]).toHaveTextContent("Roth conversions");
    fireEvent.change(input, { target: { value: "tax" } });
    const options = within(dialog).getAllByRole("option");
    expect(options.length).toBeGreaterThan(1);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(within(dialog).getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options[1].id);
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(within(dialog).getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body).not.toHaveClass("help-scroll-lock");
    expect(opener).toHaveFocus();
  });

  it("opens with ⌘K on the hub, ignores the slash key while typing and traps Tab", () => {
    render(<HelpPage />);
    const field = screen.getByLabelText("Search help");
    fireEvent.keyDown(field, { key: "/" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    const dialog = screen.getByRole("dialog", { name: "Help search" });
    const close = within(dialog).getByRole("button", { name: "Close" });
    close.focus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(within(dialog).getByRole("combobox")).toHaveFocus();
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
