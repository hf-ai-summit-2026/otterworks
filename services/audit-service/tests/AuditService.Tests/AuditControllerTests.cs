using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.HttpResults;
using Moq;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditControllerTests
{
    private static Mock<IAuditService> ServiceReturningEmptyPage()
    {
        var service = new Mock<IAuditService>();
        service
            .Setup(s => s.QueryEventsAsync(
                It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());
        return service;
    }

    [Theory]
    [InlineData(null, 1)]
    [InlineData(1, 1)]
    [InlineData(3, 3)]
    [InlineData(0, 1)]
    [InlineData(-5, 1)]
    public async Task QueryEvents_NormalizesPageToAtLeastOne(int? page, int expectedPage)
    {
        var service = ServiceReturningEmptyPage();

        var result = await AuditController.QueryEvents(null, null, null, null, null, null, page, null, service.Object);

        Assert.Equal(StatusCodes.Status200OK, ((IStatusCodeHttpResult)result).StatusCode);
        service.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, expectedPage, 20), Times.Once);
    }

    [Theory]
    [InlineData(null, 20)]
    [InlineData(0, 1)]
    [InlineData(50, 50)]
    [InlineData(500, 100)]
    public async Task QueryEvents_ClampsPageSize(int? size, int expectedSize)
    {
        var service = ServiceReturningEmptyPage();

        await AuditController.QueryEvents(null, null, null, null, null, null, null, size, service.Object);

        service.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, expectedSize), Times.Once);
    }
}
