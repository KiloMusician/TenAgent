import { createApp } from './app';

const PORT = process.env.PORT || 5000;
const app = createApp();

app.listen(PORT, () => {
  console.log(`Warung POS Backend API running on port ${PORT}`);
  console.log(`Health endpoint: http://localhost:${PORT}/api/health`);
  console.log(`OpenAPI base path: http://localhost:${PORT}/api/v1`);
});
