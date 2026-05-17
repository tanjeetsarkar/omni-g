import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center space-y-6">
        <h1 className="text-4xl font-bold text-slate-100 tracking-tight">
          Omni-G
        </h1>
        <p className="text-slate-400 text-lg">
          Threat Intelligence Knowledge Graph Platform
        </p>
        <Link
          href="/dashboard"
          className="inline-block bg-indigo-600 hover:bg-indigo-500 text-white font-semibold px-6 py-3 rounded-lg transition-colors"
        >
          Open Dashboard →
        </Link>
      </div>
    </div>
  );
}
