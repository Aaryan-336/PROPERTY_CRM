import type { Metadata } from "next";

import { LEGAL_CONTACT_EMAIL, LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Data Deletion — Balaji CRM" };

export default function DataDeletion() {
  return (
    <LegalPage title="Data Deletion">
      <p>
        If you submitted an enquiry through a Facebook or Instagram lead form and want your
        information removed from Balaji CRM, here is how.
      </p>
      <ul>
        <li>
          Email{" "}
          <a className="underline" href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>{" "}
          with the phone number or email address you used on the form.
        </li>
        <li>We will delete or anonymise your record and confirm by reply within 30 days.</li>
      </ul>
      <p>
        You can also remove the business&apos;s app from your Facebook settings under Apps and
        Websites. That stops Meta sharing future data with it, and you can still email us to delete
        what we already hold.
      </p>
    </LegalPage>
  );
}
