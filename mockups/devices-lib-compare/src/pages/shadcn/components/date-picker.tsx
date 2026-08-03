import { CalendarIcon } from "lucide-react";
import { format } from "date-fns";
import { cn } from "../lib/utils";
import { Button } from "./button";
import { Calendar } from "./calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

// Official shadcn/ui Date Picker composition: Popover + Calendar (mode="single"),
// triggered by a Button showing the formatted date or a placeholder.
// https://ui.shadcn.com/docs/components/base/date-picker
export function DatePicker({
  date,
  onDateChange,
  placeholder = "Pick a date",
  className,
}: {
  date: Date | undefined;
  onDateChange: (date: Date | undefined) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          data-empty={!date}
          className={cn(
            "w-full justify-start text-left font-normal data-[empty=true]:text-[var(--muted-foreground)]",
            className,
          )}
        >
          <CalendarIcon className="h-4 w-4" />
          {date ? format(date, "yyyy-MM-dd") : <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0">
        <Calendar mode="single" selected={date} onSelect={onDateChange} />
      </PopoverContent>
    </Popover>
  );
}
