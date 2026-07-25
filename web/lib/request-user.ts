const LOCAL_USER = "local-pilot@grant-matcher";

export function getRequestUserEmail(request: Request): string {
  return (
    request.headers.get("oai-authenticated-user-email")?.trim().toLowerCase() ||
    LOCAL_USER
  );
}
