import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { customFetch, setOrganization } from "../src/custom-fetch.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  setOrganization(null);
});

function captureRequestHeaders(): Promise<Headers> {
  return new Promise((resolve) => {
    globalThis.fetch = async (_input, init) => {
      resolve(new Headers(init?.headers));
      return new Response(null, { status: 204 });
    };

    void customFetch("/api/brands");
  });
}

test("omits the tenant header when no organization is configured", async () => {
  setOrganization(null);

  const headers = await captureRequestHeaders();

  assert.equal(headers.has("x-resound-organization"), false);
});

test("adds the configured tenant organization header", async () => {
  setOrganization(" demo ");

  const headers = await captureRequestHeaders();

  assert.equal(headers.get("x-resound-organization"), "demo");
});

test("preserves an explicit tenant organization header", async () => {
  setOrganization("demo");
  let requestHeaders: Headers | undefined;
  globalThis.fetch = async (_input, init) => {
    requestHeaders = new Headers(init?.headers);
    return new Response(null, { status: 204 });
  };

  await customFetch("/api/brands", {
    headers: { "X-Resound-Organization": "explicit-tenant" },
  });

  assert.equal(requestHeaders?.get("x-resound-organization"), "explicit-tenant");
});
