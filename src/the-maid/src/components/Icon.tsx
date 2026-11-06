// Small inline line icons (24×24 grid, drawn with currentColor) so the app
// has one consistent icon style instead of mixed emoji.
const PATHS: Record<string, string> = {
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z",
  folderOpen: "M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v1M3 7v10a2 2 0 0 0 2 2h12.5a2 2 0 0 0 1.9-1.4L21.5 12a1.5 1.5 0 0 0-1.4-2H8.4a2 2 0 0 0-1.9 1.4L4 19",
  inbox: "M3 13h5l1.5 3h5L16 13h5M5.5 5h13L21 13v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5Z",
  chevronRight: "m9 6 6 6-6 6",
  chevronDown: "m6 9 6 6 6-6",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Zm0 0v5h5",
  fileText: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Zm0 0v5h5M9 13h6M9 17h6",
  image: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm-1 12 4.5-4.5L13 16m-1-1 2.5-2.5L20 18M15.5 8.5h.01",
  video: "M4 6h11a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Zm12 4 5-3v10l-5-3",
  music: "M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm11-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  archive: "M3 4h18v4H3ZM5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4",
  code: "m8 8-4 4 4 4m8-8 4 4-4 4m-2.5-10-3 12",
  sheet: "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm-2 6h18M3 15h18M9 9v12",
  pencil: "M4 20h4L19 9l-4-4L4 16v4Zm9.5-13.5 4 4",
  trash: "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  eyeOff: "M3 3l18 18M10.6 5.1A10.6 10.6 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.8 3.6M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 2-4-4",
  expand: "M7 15l5 5 5-5M7 9l5-5 5 5",
  collapse: "M7 20l5-5 5 5M7 4l5 5 5-5",
  move: "M5 9V5h4M5 5l6 6M19 15v4h-4m4 0-6-6",
  check: "m5 12 5 5 9-10",
  x: "M6 6l12 12M18 6 6 18",
  sparkles: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  scan: "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16",
  listCheck: "M11 6h9M11 12h9M11 18h9M4 6l1.5 1.5L8 5M4 12l1.5 1.5L8 11M4 18l1.5 1.5L8 17",
  users: "M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 9v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.6 7.6 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  refresh: "M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-5v-5m0-3h.01",
  lightbulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3Z",
  broom: "M19 3 11 11M8 11l5 5M8 11c-2.5 0-5 2-5 5v5h5c3 0 5-2.5 5-5M5 21l3-4M9 21l2-3",
  arrowRight: "M5 12h14m-6-6 6 6-6 6",
  home: "M3 11 12 4l9 7M5 10v10h5v-6h4v6h5V10",
};

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 16, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

const EXT_ICONS: [IconName, string[]][] = [
  ["image", ["jpg", "jpeg", "png", "gif", "heic", "webp", "bmp", "tiff", "raw", "cr2", "nef", "svg"]],
  ["video", ["mp4", "mov", "avi", "mkv", "webm", "m4v"]],
  ["music", ["mp3", "wav", "flac", "aac", "m4a", "ogg"]],
  ["archive", ["zip", "rar", "7z", "tar", "gz", "dmg", "iso"]],
  ["code", ["js", "ts", "tsx", "py", "rs", "java", "c", "cpp", "go", "rb", "sh", "json", "html", "css"]],
  ["sheet", ["xls", "xlsx", "csv", "numbers", "ods"]],
  ["fileText", ["pdf", "doc", "docx", "txt", "md", "rtf", "pages", "odt", "ppt", "pptx", "key"]],
];

/** Icon and colour family for a file name, from its extension. */
export function fileKind(filename: string): { icon: IconName; kind: string } {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  for (const [icon, exts] of EXT_ICONS) if (exts.includes(ext)) return { icon, kind: icon };
  return { icon: "file", kind: "file" };
}
