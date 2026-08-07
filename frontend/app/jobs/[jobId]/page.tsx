import { JobStatus } from "@/components/job-status";

export default async function JobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  return (
    <main className="mx-auto max-w-7xl px-5 py-12 sm:px-8 sm:py-20">
      <JobStatus jobId={jobId} />
    </main>
  );
}

