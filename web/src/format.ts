// Display helpers. Amounts arrive as decimal strings and are formatted without floating point.

export function money(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = value.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}$${grouped}.${(fraction + "00").slice(0, 2)}`;
}

export function longDate(iso: string | null): string {
  if (!iso) return "not shown";
  const [year, month, day] = iso.split("-").map(Number);
  const names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  return `${names[month - 1]} ${day}, ${year}`;
}

// Whole cents, so a column of charges adds up exactly.
export function sumCharges(charges: string[]): string {
  const cents = charges.reduce((total, charge) => {
    const [whole, fraction = ""] = charge.replace(/[$,\s]/g, "").split(".");
    if (!/^\d*$/.test(whole) || !/^\d*$/.test(fraction)) return total;
    return total + Number(whole || 0) * 100 + Number((fraction + "00").slice(0, 2));
  }, 0);
  const text = String(cents).padStart(3, "0");
  return `${text.slice(0, -2)}.${text.slice(-2)}`;
}
