using System.Net;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddHttpClient("fetcher", client =>
{
    client.Timeout = TimeSpan.FromSeconds(15);
});

var app = builder.Build();

app.UseDefaultFiles();
app.UseStaticFiles();

app.MapGet("/api/fetch-home", async (IHttpClientFactory httpClientFactory) =>
{
    var client = httpClientFactory.CreateClient("fetcher");

    try
    {
        var html = await client.GetStringAsync("https://m.91zheli.com/");
        return Results.Text(html, "text/plain; charset=utf-8");
    }
    catch (HttpRequestException ex)
    {
        return Results.Problem($"请求目标站点失败: {ex.Message}", statusCode: (int)HttpStatusCode.BadGateway);
    }
    catch (TaskCanceledException)
    {
        return Results.Problem("请求超时，请稍后重试。", statusCode: (int)HttpStatusCode.GatewayTimeout);
    }
});

app.Run();
