import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement matchMedia; polyfill it so hooks like useIsMobile
// (window.matchMedia-based) don't crash components under test.
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  } as unknown as MediaQueryList);
}
