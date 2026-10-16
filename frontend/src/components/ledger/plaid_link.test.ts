import type { PlaidCreateOptions, PlaidGlobal } from "./plaid_link";

const mocks = vi.hoisted(() => ({ plaidLinkToken: vi.fn(), connectPlaid: vi.fn() }));
vi.mock("@/api/ledger_connections", () => ({ ledgerConnections: mocks }));

type Link = typeof import("./plaid_link");

async function fresh(): Promise<Link> {
  vi.resetModules();
  return import("./plaid_link");
}

/** A fake Plaid global; `behave` decides how Link ends once opened. */
function fakePlaid(behave: (options: PlaidCreateOptions) => void) {
  const created: PlaidCreateOptions[] = [];
  const destroy = vi.fn();
  const plaid: PlaidGlobal = {
    create: (options) => {
      created.push(options);
      return { open: () => behave(options), destroy };
    },
  };
  return { plaid, created, destroy };
}

const scripts = () => Array.from(document.head.querySelectorAll("script"));

beforeEach(() => {
  vi.clearAllMocks();
  delete window.Plaid;
  scripts().forEach((script) => script.remove());
  window.localStorage.clear();
  mocks.plaidLinkToken.mockResolvedValue({ link_token: "link-1", expiration: null });
  mocks.connectPlaid.mockResolvedValue({ id: "c1" });
});

it("adds Link's script once and resolves with the Plaid global", async () => {
  const link = await fresh();
  const first = link.loadPlaidLink();
  const second = link.loadPlaidLink();
  expect(second).toBe(first);
  expect(scripts()).toHaveLength(1);
  expect(scripts()[0].src).toBe(link.PLAID_LINK_SCRIPT);
  const { plaid } = fakePlaid(() => {});
  window.Plaid = plaid;
  scripts()[0].onload?.(new Event("load"));
  await expect(first).resolves.toBe(plaid);
  await expect(link.loadPlaidLink()).resolves.toBe(plaid);
});

it("rejects a failed load and retries with a new script", async () => {
  const link = await fresh();
  const failed = link.loadPlaidLink();
  scripts()[0].onerror?.(new Event("error"));
  await expect(failed).rejects.toThrow("Plaid Link did not load. Try again.");
  expect(scripts()).toHaveLength(0);
  const empty = link.loadPlaidLink();
  scripts()[0].onload?.(new Event("load"));
  await expect(empty).rejects.toThrow("Plaid Link did not load.");
  void link.loadPlaidLink();
  expect(scripts()).toHaveLength(1);
});

it("opens Link and reports success, institution and exit", async () => {
  const link = await fresh();
  const success = fakePlaid((options) =>
    options.onSuccess("public-1", { institution: { name: "Synthetic Bank" } }),
  );
  window.Plaid = success.plaid;
  await expect(link.openPlaidLink("link-1")).resolves.toEqual({
    publicToken: "public-1",
    institutionName: "Synthetic Bank",
  });
  expect(success.created[0].token).toBe("link-1");
  expect(success.created[0]).not.toHaveProperty("receivedRedirectUri");
  expect(success.destroy).toHaveBeenCalled();
  const exit = fakePlaid((options) => options.onExit(null));
  window.Plaid = exit.plaid;
  await expect(
    link.openPlaidLink("link-1", "https://app.example/plaid/oauth?oauth_state_id=s"),
  ).resolves.toBeNull();
  expect(exit.created[0].receivedRedirectUri).toBe(
    "https://app.example/plaid/oauth?oauth_state_id=s",
  );
  window.Plaid = fakePlaid((options) => options.onSuccess("public-2", {})).plaid;
  await expect(link.openPlaidLink("link-1")).resolves.toEqual({
    publicToken: "public-2",
    institutionName: null,
  });
});

it("saves, takes and expires the OAuth session", async () => {
  const link = await fresh();
  link.savePlaidSession("link-1", "c1");
  const taken = link.takePlaidSession();
  expect(taken).toMatchObject({ linkToken: "link-1", connectionId: "c1" });
  expect(link.takePlaidSession()).toBeNull();
  link.savePlaidSession("link-2", null);
  expect(link.takePlaidSession(Date.now() + 5 * 60 * 60 * 1000)).toBeNull();
  for (const raw of [
    "not json",
    JSON.stringify({ linkToken: "", savedAt: 1 }),
    JSON.stringify({ linkToken: "x" }),
  ]) {
    window.localStorage.setItem("coastmath.plaid_link", raw);
    expect(link.takePlaidSession()).toBeNull();
  }
  window.localStorage.setItem(
    "coastmath.plaid_link",
    JSON.stringify({ linkToken: "x", savedAt: Date.now(), connectionId: 7 }),
  );
  expect(link.takePlaidSession()?.connectionId).toBeNull();
});

it("survives blocked storage", async () => {
  const link = await fresh();
  const spies = [
    vi.spyOn(Storage.prototype, "setItem"),
    vi.spyOn(Storage.prototype, "getItem"),
    vi.spyOn(Storage.prototype, "removeItem"),
  ];
  spies.forEach((spy) =>
    spy.mockImplementation(() => {
      throw new Error("blocked");
    }),
  );
  expect(() => link.savePlaidSession("link-1", null)).not.toThrow();
  expect(() => link.clearPlaidSession()).not.toThrow();
  expect(link.takePlaidSession()).toBeNull();
  spies.forEach((spy) => spy.mockRestore());
});

it("starts a new connection and posts the public token", async () => {
  const link = await fresh();
  let saved: unknown = null;
  window.Plaid = fakePlaid((options) => {
    saved = window.localStorage.getItem("coastmath.plaid_link");
    options.onSuccess("public-1", { institution: { name: "Synthetic Bank" } });
  }).plaid;
  await expect(link.startPlaidConnection()).resolves.toEqual({ id: "c1" });
  expect(mocks.plaidLinkToken).toHaveBeenCalledWith(undefined);
  expect(JSON.parse(saved as string)).toMatchObject({ linkToken: "link-1", connectionId: null });
  expect(mocks.connectPlaid).toHaveBeenCalledWith({
    public_token: "public-1",
    institution_name: "Synthetic Bank",
  });
  expect(window.localStorage.getItem("coastmath.plaid_link")).toBeNull();
});

it("finishes update mode without exchanging a token, and does nothing on exit", async () => {
  const link = await fresh();
  window.Plaid = fakePlaid((options) => options.onSuccess("public-1", {})).plaid;
  await link.startPlaidConnection("c9");
  expect(mocks.plaidLinkToken).toHaveBeenCalledWith("c9");
  expect(mocks.connectPlaid).toHaveBeenCalledWith({ connection_id: "c9" });
  mocks.connectPlaid.mockClear();
  window.Plaid = fakePlaid((options) => options.onExit({ error_code: "USER_EXIT" })).plaid;
  await expect(link.startPlaidConnection()).resolves.toBeNull();
  expect(mocks.connectPlaid).not.toHaveBeenCalled();
});

it("resumes Link after an OAuth redirect", async () => {
  const link = await fresh();
  const fake = fakePlaid((options) => options.onSuccess("public-3", {}));
  window.Plaid = fake.plaid;
  const href = "https://app.example/plaid/oauth?oauth_state_id=s";
  await link.resumePlaidConnection(
    { linkToken: "link-1", connectionId: null, savedAt: Date.now() },
    href,
  );
  expect(fake.created[0]).toMatchObject({ token: "link-1", receivedRedirectUri: href });
  expect(mocks.connectPlaid).toHaveBeenCalledWith({
    public_token: "public-3",
    institution_name: null,
  });
});
