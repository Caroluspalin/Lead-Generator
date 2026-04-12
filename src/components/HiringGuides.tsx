import React from 'react';

const guides = [
  {
    title: 'Questions to Ask an Agency',
    bullets: [
      'What specific results have you achieved for similar clients?',
      'Who will be on our account team and how often will we meet?',
      'How do you measure success and report performance?',
      'What does the first 90 days of working together look like?',
    ],
  },
  {
    title: 'How to Read a Proposal',
    bullets: [
      'Look for clear goals, scope, and timelines that match your priorities.',
      'Check exactly what is included vs. considered an extra cost.',
      'Review how they plan to communicate and report results.',
      'Compare pricing with the value and outcomes promised, not just hours.',
    ],
  },
  {
    title: 'Red Flags to Watch For',
    bullets: [
      'Guaranteed results or unrealistic promises with no supporting plan.',
      'Lack of transparency on who does the work or where time is spent.',
      'No clear metrics, dashboards, or reporting cadence.',
      'Pressure to sign quickly without time for questions or comparison.',
    ],
  },
];

const HiringGuides: React.FC = () => {
  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Hiring Guides</h2>
        <p className="mt-1 text-sm text-slate-500 max-w-2xl">
          Use these guides to run a structured, confident process when choosing
          your next agency partner.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {guides.map((guide) => (
          <article
            key={guide.title}
            className="bg-white border border-slate-200 rounded-2xl p-4"
          >
            <h3 className="text-sm font-semibold text-slate-900 mb-2">
              {guide.title}
            </h3>
            <ul className="space-y-1.5 text-sm text-slate-600 list-disc list-inside">
              {guide.bullets.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
};

export default HiringGuides;

