# Build Stage
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["TonGPT.Engine.csproj", "./"]
RUN dotnet restore "TonGPT.Engine.csproj"
COPY . .
RUN dotnet build "TonGPT.Engine.csproj" -c Release -o /app/build

# Publish Stage
FROM build AS publish
RUN dotnet publish "TonGPT.Engine.csproj" -c Release -o /app/publish /p:UseAppHost=false

# Runtime Stage
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS final
WORKDIR /app
EXPOSE 5090
ENV ASPNETCORE_URLS=http://+:5090
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "TonGPT.Engine.dll"]
