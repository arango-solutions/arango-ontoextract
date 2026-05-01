import {
  getBasePath,
  resolvedPostLoginHref,
  withBasePath,
} from "@/lib/base-path";

const prev = process.env.NEXT_PUBLIC_BASE_PATH;

describe("base-path", () => {
  afterEach(() => {
    process.env.NEXT_PUBLIC_BASE_PATH = prev;
  });

  it("withBasePath leaves paths unchanged when env is empty", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    expect(withBasePath("/workspace")).toBe("/workspace");
    expect(withBasePath("/pipeline?runId=1")).toBe("/pipeline?runId=1");
  });

  it("withBasePath prefixes when NEXT_PUBLIC_BASE_PATH is set", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/_service/uds/_db/ontoextract/arango-ontoextract";
    expect(withBasePath("/workspace")).toBe(
      "/_service/uds/_db/ontoextract/arango-ontoextract/workspace",
    );
    expect(
      withBasePath("/pipeline?runId=abc"),
    ).toBe(
      "/_service/uds/_db/ontoextract/arango-ontoextract/pipeline?runId=abc",
    );
  });

  it("withBasePath is idempotent when path already includes base", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/prefix";
    expect(withBasePath("/prefix/workspace")).toBe("/prefix/workspace");
  });

  it("withBasePath('/') returns base + trailing slash so home anchors land on `/<prefix>/`", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/_service/uds/_db/ontoextract/arango-ontoextract";
    expect(withBasePath("/")).toBe(
      "/_service/uds/_db/ontoextract/arango-ontoextract/",
    );
  });

  it("withBasePath('/') stays '/' when no base path is configured", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    expect(withBasePath("/")).toBe("/");
  });

  it("getBasePath strips trailing slash", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/prefix/";
    expect(getBasePath()).toBe("/prefix");
  });

  it("resolvedPostLoginHref rejects protocol-relative URLs", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/prefix";
    expect(resolvedPostLoginHref("//evil.com")).toBe("/prefix/");
  });
});
