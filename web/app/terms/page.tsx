import type { Metadata } from "next";

import { LEGAL_CONTACT_EMAIL, LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Terms of Service — Balaji CRM" };

export default function Terms() {
  return (
    <LegalPage title="Terms of Service">
      <p>
        These terms apply to Balaji CRM, a private tool operated by a real estate brokerage in
        Mumbai for its own staff. By using it you agree to them.
      </p>

      <h2>Who may use it</h2>
      <p>
        Access is by invitation only. Accounts are personal. Do not share your login, and tell the
        owner immediately if you think it has been compromised.
      </p>

      <h2>Acceptable use</h2>
      <ul>
        <li>Use the system only for the brokerage&apos;s legitimate business.</li>
        <li>Handle customer information confidentially and only as needed to serve them.</li>
        <li>Do not attempt to access data or features beyond your role.</li>
        <li>Follow Meta&apos;s platform terms and advertising policies when running ads.</li>
      </ul>

      <h2>Advertising</h2>
      <p>
        Campaigns created from the CRM start paused. Spend only begins when the owner enables
        them in Meta. The owner is responsible for budgets, targeting and ad content.
      </p>

      <h2>Data</h2>
      <p>
        Customer data is handled as described in our <a className="underline" href="/privacy">Privacy Policy</a>.
      </p>

      <h2>No warranty</h2>
      <p>
        The system is provided as is. Figures such as cost per lead and reel rankings are guidance,
        not guarantees, and depend on data supplied by third parties such as Meta.
      </p>

      <h2>Limitation of liability</h2>
      <p>
        To the extent the law allows, the operator is not liable for indirect or consequential
        loss arising from use of the system.
      </p>

      <h2>Ending access</h2>
      <p>We may suspend or remove access at any time, for example if these terms are broken.</p>

      <h2>Governing law</h2>
      <p>These terms are governed by the laws of India, with courts in Mumbai having jurisdiction.</p>

      <h2>Contact</h2>
      <p>
        <a className="underline" href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>
      </p>
    </LegalPage>
  );
}
