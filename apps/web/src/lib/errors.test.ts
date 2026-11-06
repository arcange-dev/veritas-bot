import { describe, expect, it } from "vitest";
import { parseErrorDetail } from "./errors";

// The first three are copied verbatim from the running API, not written by hand.
describe("parseErrorDetail with REAL server payloads", () => {
  it("duplicate project name", () => {
    expect(parseErrorDetail({ name: ["A project with this name already exists."] }, 400)).toEqual({
      message: "Name: A project with this name already exists.",
      fields: { name: ["A project with this name already exists."] },
    });
  });
  it("blank name", () => {
    expect(parseErrorDetail({ name: ["This field may not be blank."] }, 400).fields).toEqual({
      name: ["This field may not be blank."],
    });
  });
  it("plain string detail", () => {
    expect(parseErrorDetail("Administrator role required", 403)).toEqual({
      message: "Administrator role required", fields: {},
    });
  });
});

describe("parseErrorDetail edge cases", () => {
  it("separates form-level errors from field errors", () => {
    const r = parseErrorDetail({ non_field_errors: ["Passwords differ."], email: ["Enter a valid email."] }, 400);
    expect(r.message).toBe("Passwords differ.");
    expect(r.fields).toEqual({ email: ["Enter a valid email."] });
  });
  it("handles a list", () => {
    expect(parseErrorDetail(["First problem", "Second"], 400).message).toBe("First problem");
  });
  it("flattens nested errors from list serializers", () => {
    const r = parseErrorDetail({ items: [{ name: ["Required."] }, {}] }, 400);
    expect(r.fields.items).toEqual(["Required."]);
  });
  it("names the field in the summary using a readable label", () => {
    expect(parseErrorDetail({ default_branch: ["Too long."] }, 400).message).toBe("Default branch: Too long.");
  });
  it.each([undefined, null, 42, {}, [], "", "  ", { name: [] }])("never returns an empty message for %j", (bad) => {
    expect(parseErrorDetail(bad, 502).message).toBe("Request failed (502)");
  });
});
