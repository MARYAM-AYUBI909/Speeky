-- AlterTable
ALTER TABLE "users" ADD COLUMN     "primaryTeamId" TEXT,
ADD COLUMN     "secondaryTags" TEXT[] DEFAULT ARRAY[]::TEXT[];

-- CreateTable
CREATE TABLE "teams" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "parentId" TEXT,
    "managerId" TEXT,
    "archived" BOOLEAN NOT NULL DEFAULT false,
    "archivedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "teams_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "team_assignment_history" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "teamId" TEXT NOT NULL,
    "startDate" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "endDate" TIMESTAMP(3),

    CONSTRAINT "team_assignment_history_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "teams_parentId_idx" ON "teams"("parentId");

-- CreateIndex
CREATE INDEX "teams_managerId_idx" ON "teams"("managerId");

-- CreateIndex
CREATE INDEX "team_assignment_history_userId_startDate_endDate_idx" ON "team_assignment_history"("userId", "startDate", "endDate");

-- CreateIndex
CREATE INDEX "team_assignment_history_teamId_startDate_endDate_idx" ON "team_assignment_history"("teamId", "startDate", "endDate");

-- AddForeignKey
ALTER TABLE "users" ADD CONSTRAINT "users_primaryTeamId_fkey" FOREIGN KEY ("primaryTeamId") REFERENCES "teams"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "teams" ADD CONSTRAINT "teams_parentId_fkey" FOREIGN KEY ("parentId") REFERENCES "teams"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "teams" ADD CONSTRAINT "teams_managerId_fkey" FOREIGN KEY ("managerId") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "team_assignment_history" ADD CONSTRAINT "team_assignment_history_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "team_assignment_history" ADD CONSTRAINT "team_assignment_history_teamId_fkey" FOREIGN KEY ("teamId") REFERENCES "teams"("id") ON DELETE CASCADE ON UPDATE CASCADE;
