import { redirect } from "next/navigation";

export default function QualityPage() {
  redirect("/dashboard?tab=per-ontology-quality");
}
