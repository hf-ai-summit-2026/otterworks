using Amazon.SQS;
using Amazon.SQS.Model;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class SnsConsumerTests
{
    private const string QueueName = "otterworks-audit-events-queue";
    private const string QueueUrl = "http://sqs.local/000000000000/otterworks-audit-events-queue";

    private readonly Mock<IAmazonSQS> _mockSqs = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly List<AuditEvent> _saved = new();

    public SnsConsumerTests()
    {
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => _saved.Add(e))
            .Returns(Task.CompletedTask);
        _mockSqs
            .Setup(s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new DeleteMessageResponse());
    }

    [Fact]
    public async Task SnsEnvelope_IsUnwrappedSavedAndDeleted()
    {
        GivenQueueExists();
        var body = """
            {"Type":"Notification","Message":"{\"userId\":\"u1\",\"action\":\"create\",\"resourceType\":\"document\",\"resourceId\":\"d1\",\"ipAddress\":\"10.0.0.1\",\"details\":{\"k\":\"v\"},\"timestamp\":\"2026-01-02T03:04:05Z\"}"}
            """;

        await RunWithMessagesAsync(new Message { MessageId = "m1", ReceiptHandle = "r1", Body = body });

        var saved = Assert.Single(_saved);
        Assert.Equal("m1", saved.Id);
        Assert.Equal("u1", saved.UserId);
        Assert.Equal("create", saved.Action);
        Assert.Equal("document", saved.ResourceType);
        Assert.Equal("d1", saved.ResourceId);
        Assert.Equal("10.0.0.1", saved.IpAddress);
        Assert.Equal("v", saved.Details!["k"]);
        Assert.Equal(new DateTime(2026, 1, 2, 3, 4, 5, DateTimeKind.Utc), saved.Timestamp.ToUniversalTime());
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "r1", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task RawEventWithMissingFields_UsesDefaults()
    {
        GivenQueueExists();

        await RunWithMessagesAsync(new Message { MessageId = "m2", ReceiptHandle = "r2", Body = "{}" });

        var saved = Assert.Single(_saved);
        Assert.Equal("system", saved.UserId);
        Assert.Equal("unknown", saved.Action);
        Assert.Equal("unknown", saved.ResourceType);
        Assert.Equal(string.Empty, saved.ResourceId);
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "r2", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task FileSharedEvent_IsRecordedAsShare()
    {
        GivenQueueExists();
        var body = """{"eventType":"file_shared","fileId":"f1","ownerId":"o1","sharedWithUserId":"u2"}""";

        await RunWithMessagesAsync(new Message { MessageId = "m3", ReceiptHandle = "r3", Body = body });

        var saved = Assert.Single(_saved);
        Assert.Equal("m3", saved.Id);
        Assert.Equal("o1", saved.UserId);
        Assert.Equal("share", saved.Action);
        Assert.Equal("file", saved.ResourceType);
        Assert.Equal("f1", saved.ResourceId);
        Assert.Equal("u2", saved.Details!["sharedWithUserId"]);
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "r3", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task MalformedBody_IsLeftOnQueueForRedelivery()
    {
        GivenQueueExists();

        await RunWithMessagesAsync(new Message { MessageId = "m4", ReceiptHandle = "r4", Body = "not json" });

        Assert.Empty(_saved);
        _mockSqs.Verify(s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Fact]
    public async Task RepositoryFailure_IsLeftOnQueueAndNextMessageStillProcessed()
    {
        GivenQueueExists();
        _mockRepository
            .SetupSequence(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .ThrowsAsync(new InvalidOperationException("dynamo down"))
            .Returns(Task.CompletedTask);

        await RunWithMessagesAsync(
            new Message { MessageId = "m5", ReceiptHandle = "r5", Body = "{}" },
            new Message { MessageId = "m6", ReceiptHandle = "r6", Body = "{}" });

        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "r5", It.IsAny<CancellationToken>()), Times.Never);
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "r6", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task MissingQueue_IsCreated()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new QueueDoesNotExistException("missing"));
        _mockSqs
            .Setup(s => s.CreateQueueAsync(It.Is<CreateQueueRequest>(r => r.QueueName == QueueName), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateQueueResponse { QueueUrl = QueueUrl });

        await RunWithMessagesAsync(new Message { MessageId = "m7", ReceiptHandle = "r7", Body = "{}" });

        _mockSqs.Verify(s => s.CreateQueueAsync(It.IsAny<CreateQueueRequest>(), It.IsAny<CancellationToken>()), Times.Once);
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "r7", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task QueueInitializationFailure_StopsWithoutPolling()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonSQSException("unreachable"));

        var consumer = CreateConsumer();
        await consumer.StartAsync(CancellationToken.None);
        await consumer.ExecuteTask!;

        _mockSqs.Verify(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    private void GivenQueueExists() =>
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = QueueUrl });

    private async Task RunWithMessagesAsync(params Message[] messages)
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var delivered = false;
        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((_, token) =>
            {
                if (delivered)
                {
                    cts.Cancel();
                    token.ThrowIfCancellationRequested();
                }

                delivered = true;
                return Task.FromResult(new ReceiveMessageResponse { Messages = messages.ToList() });
            });

        var consumer = CreateConsumer();
        await consumer.StartAsync(cts.Token);
        await consumer.ExecuteTask!;
    }

    private SnsConsumer CreateConsumer() => new(
        _mockSqs.Object,
        _mockRepository.Object,
        Options.Create(new AwsSettings()),
        NullLogger<SnsConsumer>.Instance);
}
