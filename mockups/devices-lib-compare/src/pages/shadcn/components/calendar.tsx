import { DayPicker, type DayPickerProps } from "react-day-picker";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../lib/utils";

// Hand-styled to match shadcn/ui's Calendar (react-day-picker v10 — class
// names below come from the current `UI` / `DayFlag` / `SelectionState`
// enums exported by react-day-picker, read from the installed package's
// type declarations rather than assumed from an older major version).
export function Calendar({ className, ...props }: DayPickerProps) {
  return (
    <DayPicker
      showOutsideDays
      className={cn("p-3", className)}
      classNames={{
        root: "text-sm",
        months: "flex flex-col",
        month: "flex flex-col gap-2",
        month_caption: "flex items-center justify-center h-8 relative",
        caption_label: "text-sm font-medium",
        nav: "flex items-center justify-between absolute inset-x-1 top-0 h-8",
        button_previous:
          "inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-30",
        button_next:
          "inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-30",
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday: "w-9 text-xs font-normal text-[var(--muted-foreground)]",
        week: "flex w-full mt-1",
        day: "w-9 h-9 p-0 text-center",
        day_button:
          "h-9 w-9 rounded-md text-sm font-normal hover:bg-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
        selected:
          "[&>button]:bg-[var(--primary)] [&>button]:text-[var(--primary-foreground)] [&>button]:hover:bg-[var(--primary)]",
        today: "[&>button]:font-semibold [&>button]:text-[var(--primary)]",
        outside: "[&>button]:text-[var(--muted-foreground)] [&>button]:opacity-40",
        disabled: "[&>button]:opacity-30 [&>button]:pointer-events-none",
        hidden: "invisible",
      }}
      components={{
        Chevron: ({ orientation, className: chevronClassName }) =>
          orientation === "left" ? (
            <ChevronLeft className={cn("h-4 w-4", chevronClassName)} />
          ) : (
            <ChevronRight className={cn("h-4 w-4", chevronClassName)} />
          ),
      }}
      {...props}
    />
  );
}
