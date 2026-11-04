/**
 * Provider settings (BYOK). The key is posted once, never read back: the list
 * only ever shows the last four characters and a validation status.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, XCircle } from "lucide-react";
import { ApiError, api, type Credential } from "@/lib/api";
import { useSession } from "@/stores/session";
import { EmptyState, Panel, StatusChip } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";

const PROVIDERS = [
  "openai", "anthropic", "google", "openrouter", "xai", "deepseek", "mistral",
  "groq", "together", "fireworks", "bedrock", "azure_openai", "ollama", "lmstudio",
  "openai_compatible",
] as const;

const NEEDS_BASE_URL = new Set(["ollama", "lmstudio", "openai_compatible", "azure_openai"]);

const tone = (status: Credential["status"]) =>
  status === "valid" ? "ok" : status === "invalid" ? "danger" : "muted";

export function ProvidersPage() {
  const orgId = useSession((s) => s.orgId);
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<string>("openai");
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["credentials", orgId],
    queryFn: () => api.credentials(orgId as string),
    enabled: Boolean(orgId),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createCredential(orgId as string, {
        provider,
        label: label || provider,
        api_key: apiKey,
        ...(NEEDS_BASE_URL.has(provider) ? { base_url: baseUrl } : {}),
      }),
    onSuccess: () => {
      setApiKey("");
      setLabel("");
      setBaseUrl("");
      setFormError(null);
      void queryClient.invalidateQueries({ queryKey: ["credentials", orgId] });
    },
    onError: (error: unknown) => {
      setFormError(error instanceof ApiError ? error.message : "Could not save the credential.");
    },
  });

  const test = useMutation({
    mutationFn: (id: string) => api.testCredential(orgId as string, id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["credentials", orgId] }),
  });

  const field =
    "h-9 w-full rounded-sm border border-subtle bg-base px-2 text-[12.5px] text-primary placeholder:text-muted";

  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Panel label="Connected providers" className="rounded-md border border-subtle">
        {list.isLoading ? (
          <p className="p-4 text-[12.5px] text-muted">Loading credentials…</p>
        ) : list.error ? (
          <p className="p-4 text-[12.5px] text-danger">Could not load credentials.</p>
        ) : list.data && list.data.results.length > 0 ? (
          <ul className="divide-y divide-subtle">
            {list.data.results.map((credential) => (
              <li key={credential.id} className="flex items-center gap-3 px-4 py-3">
                <KeyRound className="size-4 shrink-0 text-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] text-primary">
                    {credential.label || credential.provider}
                  </p>
                  <p className="tabular font-mono text-[11.5px] text-muted">
                    {credential.provider} · ••••{credential.last4}
                  </p>
                </div>
                <StatusChip tone={tone(credential.status)}>{credential.status}</StatusChip>
                <button
                  type="button"
                  onClick={() => test.mutate(credential.id)}
                  disabled={test.isPending}
                  className="h-7 rounded-sm border border-subtle px-2 text-[12px] text-secondary hover:border-strong hover:text-primary disabled:opacity-50"
                >
                  {test.isPending ? "Testing…" : "Test"}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No providers connected"
            body="Add a provider key to let your agents plan and write code. Keys are encrypted at rest and only the last four characters are ever shown."
          />
        )}
        {test.data ? (
          <p className={cn("flex items-center gap-1.5 px-4 pb-3 text-[12px]",
            test.data.ok ? "text-ok" : "text-danger")}>
            {test.data.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
            {test.data.ok
              ? `Connection valid${test.data.model_count ? `, ${test.data.model_count} models visible` : ""}`
              : `${test.data.error_code}: ${test.data.detail}`}
          </p>
        ) : null}
      </Panel>

      <Panel label="Add a credential" className="rounded-md border border-subtle">
        <form
          className="flex flex-col gap-3 p-4"
          onSubmit={(event) => {
            event.preventDefault();
            setFormError(null);
            create.mutate();
          }}
        >
          <div>
            <label htmlFor="provider" className="panel-label mb-1 block">Provider</label>
            <select id="provider" className={field} value={provider}
              onChange={(event) => setProvider(event.target.value)}>
              {PROVIDERS.map((slug) => (
                <option key={slug} value={slug}>{slug}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="label" className="panel-label mb-1 block">Label</label>
            <input id="label" className={field} value={label} placeholder="work key"
              onChange={(event) => setLabel(event.target.value)} />
          </div>
          <div>
            <label htmlFor="api-key" className="panel-label mb-1 block">API key</label>
            <input id="api-key" className={field} type="password" value={apiKey}
              autoComplete="off" required minLength={8}
              onChange={(event) => setApiKey(event.target.value)} />
            <p className="mt-1 text-[11px] text-muted">
              Sent once over TLS, encrypted with AES before storage, never returned.
            </p>
          </div>
          {NEEDS_BASE_URL.has(provider) ? (
            <div>
              <label htmlFor="base-url" className="panel-label mb-1 block">Base URL</label>
              <input id="base-url" className={field} value={baseUrl}
                placeholder="http://localhost:11434"
                onChange={(event) => setBaseUrl(event.target.value)} />
            </div>
          ) : null}
          {formError ? <p className="text-[12px] text-danger">{formError}</p> : null}
          <button type="submit" disabled={create.isPending}
            className="h-9 rounded-sm bg-accent text-[12.5px] font-medium text-white hover:bg-accent-soft disabled:opacity-50">
            {create.isPending ? "Saving…" : "Save credential"}
          </button>
        </form>
      </Panel>
    </div>
  );
}
