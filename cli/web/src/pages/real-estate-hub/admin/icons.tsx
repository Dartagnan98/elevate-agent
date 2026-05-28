import React from "react";

type IconProps = React.SVGProps<SVGSVGElement>;

function icon(paths: string[], viewBox = "0 0 24 24") {
  return function Icon(props: IconProps) {
    return (
      <svg
        viewBox={viewBox}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
        {...props}
      >
        {paths.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </svg>
    );
  };
}

export const Home = icon(["M3 11.5 12 4l9 7.5", "M5 10v10h14V10"]);
export const Users = icon(["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"]);
export const Briefcase = icon(["M3 8h18v12H3z", "M8 8V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v3"]);
export const Megaphone = icon(["M3 11v4a4 4 0 0 0 4 4l1 -2v-8z", "M21 5 7 11v4l14 6z", "M11 19v3"]);
export const Bot = icon(["M8 11h8", "M9 14h6", "M6 8h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z", "M12 4v4", "M10 4h4"]);
export const ListChecks = icon(["M3 17l2 2 4-4", "M3 7l2 2 4-4", "M13 6h8", "M13 12h8", "M13 18h8"]);
export const Brain = icon(["M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3 2.5 2.5 0 0 1 2.46-2.04Z", "M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"]);
export const Puzzle = icon(["M19 11a2 2 0 0 0 0-4h-1V5a2 2 0 0 0-2-2h-2V2a2 2 0 1 0-4 0v1H8a2 2 0 0 0-2 2v2H5a2 2 0 1 0 0 4h1v2a2 2 0 0 0 2 2h2v1a2 2 0 1 0 4 0v-1h2a2 2 0 0 0 2-2v-2z"]);
export const Clock = icon(["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M12 7v5l3 2"]);
export const Plus = icon(["M12 5v14", "M5 12h14"]);
export const Search = icon(["M11 3a8 8 0 1 1 0 16 8 8 0 0 1 0-16z", "M21 21l-4.3-4.3"]);
export const PanelLeft = icon(["M3 4h18v16H3z", "M9 4v16"]);
export const Chevron = icon(["M6 9l6 6 6-6"]);
export const ChevronRight = icon(["M9 6l6 6-6 6"]);
export const ChevronUp = icon(["M6 15l6-6 6 6"]);
export const Settings = icon(["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8L4.2 7.2A2 2 0 1 1 7 4.4l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"]);
export const Terminal = icon(["M4 17l6-6-6-6", "M12 19h8"]);
export const Globe = icon(["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M3 12h18", "M12 3a13 13 0 0 1 0 18", "M12 3a13 13 0 0 0 0 18"]);
export const Send = icon(["M22 2 11 13", "M22 2l-7 20-4-9-9-4z"]);
export const Paperclip = icon(["M21.4 11 12 20.4a5.6 5.6 0 0 1-8-8l9.4-9.4a4 4 0 0 1 5.6 5.6L9.6 18.1a2 2 0 1 1-2.8-2.8L15.5 6.5"]);
export const Mic = icon(["M12 2a3 3 0 0 0-3 3v7a3 3 0 1 0 6 0V5a3 3 0 0 0-3-3z", "M5 11a7 7 0 0 0 14 0", "M12 18v3", "M9 21h6"]);
export const Shield = icon(["M12 3 4 6v6c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V6z"]);
export const ShieldAlert = icon(["M12 3 4 6v6c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V6z", "M12 8v4", "M12 16h.01"]);
export const Pin = icon(["M12 17v5", "M9 3l6 0", "M10 3v6L5 14h14L14 9V3"]);

export function PinFilled(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
      <path d="M14 2H10v6L5 13v2h6v7l1 1 1-1v-7h6v-2l-5-5z" />
    </svg>
  );
}

export const File = icon(["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6"]);
export const FileCode = icon(["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M10 12l-2 2 2 2", "M14 12l2 2-2 2"]);
export const Image = icon(["M3 5h18v14H3z", "M3 16l5-5 4 4 3-3 6 6", "M9 9a1 1 0 1 1-2 0 1 1 0 0 1 2 0z"]);
export const Diff = icon(["M12 3v18", "M3 12h18", "M6 6l2 2", "M16 16l2 2", "M18 6l-2 2", "M8 16l-2 2"]);
export const ChevronDown = icon(["M6 9l6 6 6-6"]);
export const Sparkles = icon(["M12 3l1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5z", "M19 17l.7 2 2 .7-2 .7L19 22l-.7-1.6-2-.7 2-.7z", "M5 4l.5 1.5L7 6l-1.5.5L5 8l-.5-1.5L3 6l1.5-.5z"]);
export const MoreHoriz = icon(["M5 12h.01", "M12 12h.01", "M19 12h.01"]);
export const Pencil = icon(["M12 20h9", "M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"]);
export const Trash = icon(["M3 6h18", "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2", "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"]);
export const Telegram = icon(["M21 4 2 11l6 2 2 6 4-4 6 5z"]);
export const Wrench = icon(["M14.7 6.3a4 4 0 0 1-5.4 5.4l-6 6a2 2 0 1 0 3 3l6-6a4 4 0 0 1 5.4-5.4l-2 2 2 2 2-2-2-2z"]);
export const Boxes = icon(["M3 7l3-2 3 2-3 2zM15 7l3-2 3 2-3 2zM9 17l3-2 3 2-3 2z", "M6 5v8", "M18 5v8", "M12 13v8"]);
export const CheckCheck = icon(["M3 12l4 4 7-7", "M9 12l4 4 8-8"]);
export const Eye = icon(["M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z", "M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"]);
export const Database = icon(["M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3v12c0 1.7-3.6 3-8 3s-8-1.3-8-3z", "M4 6c0 1.7 3.6 3 8 3s8-1.3 8-3", "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"]);
export const Cron = icon(["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z", "M12 7v5l3 2", "M6 3 3 6", "M18 3l3 3"]);
export const Discord = icon(["M5 7c4-2 10-2 14 0", "M5 17c4 2 10 2 14 0", "M9 11.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z", "M18 11.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z", "M7 7l-1 10 4 1", "M17 7l1 10-4 1"]);
export const AlertTriangle = icon(["M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z", "M12 9v4", "M12 17h.01"]);
export const Pause = icon(["M6 4h4v16H6z", "M14 4h4v16h-4z"]);
export const BarChart = icon(["M3 21V10", "M9 21V4", "M15 21V14", "M21 21V8"]);
export const BookOpen = icon(["M2 4h7a3 3 0 0 1 3 3v14a2 2 0 0 0-2-2H2z", "M22 4h-7a3 3 0 0 0-3 3v14a2 2 0 0 1 2-2h8z"]);
export const KeyRound = icon(["M2 18l8-8", "M5 15l3 3", "M14 6a4 4 0 1 1 6 6 4 4 0 0 1-6-6z"]);
export const FileText = icon(["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M8 13h8", "M8 17h5"]);
export const Refresh = icon(["M21 12a9 9 0 0 1-15.5 6.3L3 16", "M3 12a9 9 0 0 1 15.5-6.3L21 8", "M21 3v5h-5", "M3 21v-5h5"]);
export const Download = icon(["M12 4v12", "M7 11l5 5 5-5", "M4 20h16"]);
export const Moon = icon(["M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"]);
export const Sun = icon(["M12 4v2", "M12 18v2", "M4.93 4.93l1.41 1.41", "M17.66 17.66l1.41 1.41", "M2 12h2", "M20 12h2", "M6.34 17.66l-1.41 1.41", "M19.07 4.93l-1.41 1.41", "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"]);
export const User = icon(["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"]);
export const LogOut = icon(["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5", "M21 12H9"]);
