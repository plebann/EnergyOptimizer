# Contributing

Contributions are welcome! Here are some ways you can contribute:

## Issues

If you find a bug or have a feature request, please create an issue.

## Pull Requests

1. Fork the repository
2. Create a new branch for your feature or bugfix
3. Make your changes
4. Run the tests and linters
5. Submit a pull request

## Development Setup

This project uses VS Code devcontainers for development. To get started:

1. Install Docker and VS Code with the Remote - Containers extension
2. Open the project in VS Code
3. Click "Reopen in Container" when prompted
4. The development environment will be set up automatically

## Code Quality

- Use Ruff for linting and formatting
- Follow Home Assistant coding standards
- Write tests for new features
- Update documentation as needed

## Testing

Run tests with:
```bash
pytest
```

## Linting

Lint code with:
```bash
ruff check custom_components/energy_optimizer
```

Format code with:
```bash
ruff format custom_components/energy_optimizer
```
