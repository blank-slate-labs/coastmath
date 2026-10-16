import { create } from "zustand";

type ThemePreference = "light" | "dark" | "system";

interface ThemeState {
  preference: ThemePreference;
  setPreference: (pref: ThemePreference) => void;
}

function applyTheme(pref: ThemePreference) {
  const resolved =
    pref === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : pref;
  document.documentElement.setAttribute("data-theme", resolved);
}

export const useThemeStore = create<ThemeState>((set) => {
  const saved = (localStorage.getItem("coastmath:theme") as ThemePreference) ?? "system";
  // Apply on load
  applyTheme(saved);

  return {
    preference: saved,
    setPreference: (pref) => {
      localStorage.setItem("coastmath:theme", pref);
      applyTheme(pref);
      set({ preference: pref });
    },
  };
});
