/** Newdru wordmark: uses the uploaded logo asset if available, otherwise the styled text. */
export default function NewdruLogo({ size = "md", tagline = false, dark = false }) {
  const sizes = {
    sm: { text: "text-xl", tag: "text-[0.6rem]" },
    md: { text: "text-2xl", tag: "text-[0.65rem]" },
    lg: { text: "text-4xl", tag: "text-xs" },
    xl: { text: "text-5xl", tag: "text-sm" },
  };
  const s = sizes[size] || sizes.md;
  return (
    <div className="inline-flex flex-col items-start leading-none select-none" data-testid="newdru-logo">
      <span
        className={`font-brand ${s.text}`}
        style={{ color: dark ? "#FFFFFF" : "#F0544A" }}
      >
        NEWDRU
      </span>
      {tagline && (
        <span
          className={`font-brand mt-1 ${s.tag}`}
          style={{ color: dark ? "#FFB4AF" : "#F0544A", letterSpacing: "0.15em" }}
        >
          POWER YOUR STYLE
        </span>
      )}
    </div>
  );
}
