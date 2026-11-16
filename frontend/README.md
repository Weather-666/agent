This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open the following URLs in your browser:

- User site: [http://localhost:3000/](http://localhost:3000/)
- Admin login: [k](http://localhost:3000/admin/login)

## Platform User Invitation and Activation

Platform users are created by an existing platform admin or operator, then activated by the invited user.

### 1. Admin creates an invitation

1. Log in to the admin console:

   [http://localhost:3000/admin/login](http://localhost:3000/admin/login)

2. Open:

   `用户与权限 -> 平台人员`

3. Click `添加平台人员`.

4. Fill in the invited user's email, name, and platform roles.

5. After creation succeeds, the page shows an activation link like:

   ```text
   http://localhost:3000/platform/activate?token=one-time-token
   ```

6. Copy this link and send it to the invited platform user.

### 2. Invited user activates the account

The invited user opens the activation link in a browser:

```text
http://localhost:3000/platform/activate?token=one-time-token
```

On this page, the invited user sets a new password and activates the account.

The activation page calls:

```http
POST /api/v1/users/platform/activate
```

After activation succeeds, the user is redirected to:

[http://localhost:3000/admin/login](http://localhost:3000/admin/login)

The user can then log in with their invited email and newly set password.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
