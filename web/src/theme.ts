import { theme, type ThemeConfig } from "antd";

/**
 * The ARICHDS design tokens — set once, inherited by every module that follows
 * (SPEC §3.1: "theme tokens วางที่นี่ครั้งเดียว ทุกโมดูลถัดไปสืบทอด").
 *
 * Deep teal primary, compact density, light mode. Combining the default and
 * compact algorithms is what makes this read as a re-themed product rather than
 * stock Ant Design — the deliberate choice from M0's mockup comparison.
 */
export const arichdsTheme: ThemeConfig = {
  token: {
    colorPrimary: "#0f766e",
    borderRadius: 6,
    fontSize: 14,
  },
  algorithm: [theme.defaultAlgorithm, theme.compactAlgorithm],
};

/** Header height, shared by the shell layout and its spacer. */
export const HEADER_HEIGHT = 48;

/** How often the Monitor page refetches the latest readings, in milliseconds. */
export const MONITOR_REFRESH_MS = 10_000;

/** How often the app re-checks license state while sitting on Activation. */
export const LICENSE_POLL_MS = 5_000;
