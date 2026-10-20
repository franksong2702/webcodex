import assert from "node:assert/strict";
import test from "node:test";
import { CSS_BEGIN, CSS_END, JS_BEGIN, JS_END, normalizeLineEndings, replaceSelectionRegion } from "../scripts/build-selection-motion.mjs";

test("selection builder compares canonical LF regions across Windows CRLF checkouts", () => {
  const checkedOut = `<style>${CSS_BEGIN}\r\nnew css\r\n${CSS_END}</style><script>${JS_BEGIN}\r\nnew js\r\n${JS_END}</script>`;
  const canonical = normalizeLineEndings(checkedOut);
  const result = replaceSelectionRegion(replaceSelectionRegion(canonical, "new css", CSS_BEGIN, CSS_END), "new js", JS_BEGIN, JS_END);
  assert.equal(result, canonical);
  assert.equal(normalizeLineEndings("a\r\nb\n"), "a\nb\n");
});

test("selection builder only replaces its strict generated region", () => {
  const original = `<style>${CSS_BEGIN}\nold css\n${CSS_END}</style><script>${JS_BEGIN}\nold js\n${JS_END}\ncontroller()</script>`;
  const css = replaceSelectionRegion(original, "new css", CSS_BEGIN, CSS_END);
  const result = replaceSelectionRegion(css, "new js", JS_BEGIN, JS_END);
  assert.equal(result, `<style>${CSS_BEGIN}\nnew css\n${CSS_END}</style><script>${JS_BEGIN}\nnew js\n${JS_END}\ncontroller()</script>`);
  assert.equal(replaceSelectionRegion(result, "new js", JS_BEGIN, JS_END), result);
  assert.throws(() => replaceSelectionRegion("missing", "new", JS_BEGIN, JS_END), /exactly one/);
  assert.throws(() => replaceSelectionRegion(`${JS_END}${JS_BEGIN}`, "new", JS_BEGIN, JS_END), /order/);
  assert.throws(() => replaceSelectionRegion(`${JS_BEGIN}${JS_END}${JS_END}`, "new", JS_BEGIN, JS_END), /exactly one/);
  assert.throws(() => replaceSelectionRegion(original, JS_END, JS_BEGIN, JS_END), /reserved/);
});
