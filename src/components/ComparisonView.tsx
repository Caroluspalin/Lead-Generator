import React from 'react';
import { usePipeline } from '../context/PipelineContext';
import { ExternalLink, MapPin, Phone } from 'lucide-react';

const ComparisonView: React.FC = () => {
  const { savedAgencies } = usePipeline();

  if (savedAgencies.length === 0) {
    return (
      <section className="bg-white border border-slate-200 rounded-2xl p-8 text-center text-slate-500 text-sm">
        <p className="mb-2">
          No agencies selected yet. Save agencies from the search results to
          compare them side-by-side.
        </p>
      </section>
    );
  }

  return (
    <section>
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">
          Comparison Tool
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Review your saved agencies next to each other to make a confident
          hiring decision.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-2xl p-4 overflow-x-auto">
        <div className="grid grid-flow-col auto-cols-[260px] gap-4">
          {savedAgencies.map((agency) => {
            const website = agency.website
              ? agency.website.startsWith('http')
                ? agency.website
                : `http://${agency.website}`
              : '';

            return (
              <article
                key={agency.id}
                className="border border-slate-200 rounded-xl p-3 text-sm flex flex-col gap-2"
              >
                <div>
                  <h3 className="font-semibold text-slate-900">{agency.name}</h3>
                  <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                    <MapPin size={11} />
                    <span className="truncate">{agency.address ?? agency.city}</span>
                  </p>
                </div>

                <div className="text-xs text-slate-600 space-y-1">
                  <p>
                    <span className="font-medium">Pipeline:</span>{' '}
                    {agency.pipeline_status}
                  </p>
                  {agency.website_status && (
                    <p>
                      <span className="font-medium">Website:</span>{' '}
                      {agency.website_status}
                    </p>
                  )}
                  {agency.phone && (
                    <p className="flex items-center gap-1">
                      <Phone size={11} className="text-slate-400" />
                      {agency.phone}
                    </p>
                  )}
                </div>

                <div className="text-xs text-slate-600">
                  <p className="font-medium mb-1">Notes</p>
                  <p className="line-clamp-5 whitespace-pre-line bg-slate-50 border border-slate-200 rounded-md px-2 py-1 min-h-[3.5rem]">
                    {agency.notes || (
                      <span className="text-slate-400 italic">
                        No notes yet.
                      </span>
                    )}
                  </p>
                </div>

                <div className="mt-auto pt-1 text-xs">
                  {website ? (
                    <a
                      href={website}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
                    >
                      Visit website
                      <ExternalLink size={11} />
                    </a>
                  ) : (
                    <span className="text-slate-400">No website</span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default ComparisonView;

