// Aliases over the generated OpenAPI types (src/lib/api-schema.d.ts). Never hand-write these.
import type { components } from "./api-schema";

type S = components["schemas"];
export type AskResult = S["AskResult"];
export type Verdict = S["Verdict"];
export type Reference = S["Reference"];
export type DocumentOut = S["DocumentOut"];
export type DocumentList = S["DocumentList"];
export type Limits = S["Limits"];
export type AssistantLink = S["AssistantLink"];
export type RegeneratedAssistant = S["RegeneratedAssistant"];
export type Usage = S["Usage"];
export type QuestionOut = S["QuestionOut"];
export type MeResponse = S["MeResponse"];
export type PublicAssistant = S["PublicAssistant"];
export type UploadAccepted = S["UploadAccepted"];
export type Route = NonNullable<AskResult["route"]>;
export type Outcome = AskResult["outcome"];
