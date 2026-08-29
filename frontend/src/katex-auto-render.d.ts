declare module 'katex/dist/contrib/auto-render' {
  function renderMathInElement(
    el: HTMLElement,
    options?: {
      delimiters?: Array<{ left: string; right: string; display: boolean }>;
      throwOnError?: boolean;
    },
  ): void;
  export default renderMathInElement;
}
