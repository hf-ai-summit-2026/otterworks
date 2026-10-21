namespace OtterWorks.AuditService.Services;

/// <summary>An audit record. Init-only: records are immutable once created.</summary>
public class AuditEvent
{
    public string Id { get; init; } = string.Empty;
    public string UserId { get; init; } = string.Empty;
    public string Action { get; init; } = string.Empty; // create, read, update, delete, share, login, logout
    public string ResourceType { get; init; } = string.Empty; // file, document, folder, user, permission
    public string ResourceId { get; init; } = string.Empty;
    public Dictionary<string, string>? Details { get; init; }
    public string? IpAddress { get; init; }
    public string? UserAgent { get; init; }
    public DateTime Timestamp { get; init; }
}

public class AuditEventPage
{
    public List<AuditEvent> Events { get; set; } = new();
    public int Total { get; set; }
    public int Page { get; set; }
    public int PageSize { get; set; }
}
