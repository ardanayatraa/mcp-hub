// Access rules read by middleware/session.global.ts.
declare module "#app" {
  interface PageMeta {
    /** Open without signing in. */
    public?: boolean;
    /** Hidden from auditors, who have read-only access. */
    write?: boolean;
    /** Super admins only. */
    superAdmin?: boolean;
  }
}

export {};
