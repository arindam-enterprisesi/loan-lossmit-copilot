import { redirect } from "next/navigation";

// Two copilots share one app. Land on Loan Processing; the sidebar switches to Loss Mitigation.
export default function Home() {
  redirect("/underwriting");
}
