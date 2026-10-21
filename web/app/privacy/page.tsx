import type { Metadata } from "next";

import { LEGAL_CONTACT_EMAIL, LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Privacy Policy — Balaji CRM" };

export default function Privacy() {
  return (
    <LegalPage title="Privacy Policy">
      <p>
        Balaji CRM is a private customer-relationship tool used by a real estate brokerage in
        Mumbai to manage property enquiries, listings, site visits and advertising. This policy
        explains what information it handles and why.
      </p>

      <h2>Information we collect</h2>
      <ul>
        <li>
          <b>Enquiries you send us.</b> Name, phone number, email address, property preferences
          (such as BHK and preferred areas) and any other answers you give when you submit a Meta
          (Facebook or Instagram) lead form, call us, or message us.
        </li>
        <li>
          <b>Notes about your enquiry.</b> Call and visit notes our team records while helping you
          find a property.
        </li>
        <li>
          <b>Advertising data.</b> For the business&apos;s own ad accounts, campaign names, spend and
          performance figures, and public reel metrics from the business&apos;s own Instagram
          account, received through Meta&apos;s platform with the business owner&apos;s permission.
        </li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To contact you about the properties you asked about and arrange site visits.</li>
        <li>To avoid duplicate records and keep your enquiry history in one place.</li>
        <li>To measure which advertising produces genuine enquiries.</li>
      </ul>
      <p>We do not sell your information and we do not use it to build profiles for third parties.</p>

      <h2>Meta platform data</h2>
      <p>
        The business owner connects their Facebook Page, Instagram account and ad account to Balaji
        CRM. Access tokens are stored encrypted. When you submit a lead form, Meta tells the CRM
        and the CRM retrieves that submission. We use Meta data only to run the business&apos;s own
        advertising and enquiry handling, and not for any other purpose.
      </p>

      <h2>Who can see it</h2>
      <p>
        Only the brokerage&apos;s own staff, with access limited by role. We share information with
        service providers that host the system (for example cloud hosting and database
        providers) and only so they can run it, or where the law requires.
      </p>

      <h2>How long we keep it</h2>
      <p>
        We keep enquiry records while they remain useful for the brokerage&apos;s business and
        delete or anonymise them on request.
      </p>

      <h2>Your choices</h2>
      <p>
        You can ask to see, correct or delete the information we hold about you. See our{" "}
        <a className="underline" href="/data-deletion">data deletion page</a> or email{" "}
        <a className="underline" href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>.
      </p>

      <h2>Security</h2>
      <p>
        Data is stored in a password-protected database, transmitted over HTTPS, and access is
        logged. No system is perfectly secure, but we take reasonable steps to protect it.
      </p>

      <h2>Changes</h2>
      <p>We may update this policy and will change the date above when we do.</p>

      <h2>Contact</h2>
      <p>
        <a className="underline" href={`mailto:${LEGAL_CONTACT_EMAIL}`}>{LEGAL_CONTACT_EMAIL}</a>
      </p>
    </LegalPage>
  );
}
